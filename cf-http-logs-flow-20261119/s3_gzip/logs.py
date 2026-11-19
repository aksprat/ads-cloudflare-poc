"""NDJSON lines into the request_log table's shape, and the lines that cannot be (pure pyarrow)."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from typing import Any

import pyarrow as pa

ROW = "row"
OBJECT_KEY_COLUMN = "source_ref"
LINE_NO_COLUMN = "source_offset"
LINE = "line"

BLANK_LINE = "author.blank_line"
MALFORMED_JSON = "author.malformed_json"
NOT_AN_OBJECT = "author.not_an_object"
MISSING_RAY_ID = "author.missing_ray_id"
DUPLICATE_IN_OBJECT = "author.duplicate_in_object"
BAD_VALUE = "author.bad_value"

# (table column, Iceberg type in sink.ddl, field name in the NDJSON line)
FIELDS = [
    ("ray_id", "VARCHAR", "RayID"),
    ("edge_start_timestamp", "TIMESTAMPTZ", "EdgeStartTimestamp"),
    ("edge_end_timestamp", "TIMESTAMPTZ", "EdgeEndTimestamp"),
    ("zone_name", "VARCHAR", "ZoneName"),
    ("client_request_host", "VARCHAR", "ClientRequestHost"),
    ("client_request_method", "VARCHAR", "ClientRequestMethod"),
    ("client_request_path", "VARCHAR", "ClientRequestPath"),
    ("client_request_uri", "VARCHAR", "ClientRequestURI"),
    ("client_request_protocol", "VARCHAR", "ClientRequestProtocol"),
    ("client_request_referer", "VARCHAR", "ClientRequestReferer"),
    ("client_request_user_agent", "VARCHAR", "ClientRequestUserAgent"),
    ("client_request_bytes", "BIGINT", "ClientRequestBytes"),
    ("edge_response_status", "BIGINT", "EdgeResponseStatus"),
    ("edge_response_bytes", "BIGINT", "EdgeResponseBytes"),
    ("edge_response_body_bytes", "BIGINT", "EdgeResponseBodyBytes"),
    ("edge_response_content_type", "VARCHAR", "EdgeResponseContentType"),
    ("origin_response_status", "BIGINT", "OriginResponseStatus"),
    ("security_action", "VARCHAR", "SecurityAction"),
    ("edge_time_to_first_byte_ms", "BIGINT", "EdgeTimeToFirstByteMs"),
    ("origin_response_duration_ms", "BIGINT", "OriginResponseDurationMs"),
    ("client_tcp_rtt_ms", "BIGINT", "ClientTCPRTTMs"),
    ("cache_cache_status", "VARCHAR", "CacheCacheStatus"),
    ("cache_response_status", "BIGINT", "CacheResponseStatus"),
    ("client_asn", "BIGINT", "ClientASN"),
    ("client_country", "VARCHAR", "ClientCountry"),
    ("client_region_code", "VARCHAR", "ClientRegionCode"),
    ("client_device_type", "VARCHAR", "ClientDeviceType"),
    ("client_ip", "VARCHAR", "ClientIP"),
    ("client_ssl_protocol", "VARCHAR", "ClientSSLProtocol"),
    ("ja3_hash", "VARCHAR", "JA3Hash"),
    ("edge_colo_id", "BIGINT", "EdgeColoID"),
    ("edge_colo_code", "VARCHAR", "EdgeColoCode"),
    ("origin_ip", "VARCHAR", "OriginIP"),
]
COLUMNS = [c for c, _, _ in FIELDS]
PROVENANCE = ["object_key", "line_no", "ingested_at"]
CLIENT_IP = "client_ip"
INT64_MIN, INT64_MAX = -(2**63), 2**63 - 1


class BadValue(ValueError):
    pass


def hash_ip(ip: str) -> str:
    """A stable stand-in for an IP, so rows still group by client without storing the address.

    This is a pseudonym, not anonymization: an IPv4 address can be recovered by hashing every possible address.
    """
    return hashlib.sha256(ip.encode()).hexdigest()[:16]


def _timestamp(value: Any) -> dt.datetime:
    # Logpush writes RFC 3339 (2026-11-10T00:00:01Z) or epoch seconds/nanoseconds.
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = value / 1e9 if value > 1e12 else value
        return dt.datetime.fromtimestamp(seconds, dt.timezone.utc)
    parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def _cast(kind: str, value: Any) -> Any:
    if value is None or value == "":
        return None
    try:
        if kind == "BIGINT":
            if isinstance(value, bool) or (isinstance(value, float) and not value.is_integer()):
                raise BadValue
            number = int(value)
            if not INT64_MIN <= number <= INT64_MAX:
                raise BadValue
            return number
        if kind == "TIMESTAMPTZ":
            return _timestamp(value)
        if kind == "BOOLEAN":
            if isinstance(value, bool):
                return value
            raise BadValue
        if kind == "DOUBLE":
            return float(value)
    except (ValueError, TypeError, OverflowError, OSError, BadValue):
        raise BadValue(kind) from None
    # VARCHAR: arrays, objects and booleans become JSON text.
    return json.dumps(value, separators=(",", ":")) if isinstance(value, (list, dict, bool)) else str(value)


def parse_line(line: bytes) -> tuple[dict[str, Any] | None, str | None]:
    """``(row, None)`` for a good line, ``(None, reason)`` for a bad one. The row has the table's data columns only."""
    try:
        obj = json.loads(line)
    except (ValueError, RecursionError):  # not JSON, not UTF-8, or nested past the interpreter's limit
        return None, MALFORMED_JSON
    if not isinstance(obj, dict):
        return None, NOT_AN_OBJECT
    if not obj.get("RayID"):
        return None, MISSING_RAY_ID
    row: dict[str, Any] = {}
    for column, kind, field in FIELDS:
        try:
            row[column] = _cast(kind, obj.get(field))
        except BadValue:
            return None, "%s.%s" % (BAD_VALUE, column)
    if row["edge_start_timestamp"] is None:
        return None, "%s.edge_start_timestamp" % BAD_VALUE
    if row[CLIENT_IP] is not None:
        row[CLIENT_IP] = hash_ip(row[CLIENT_IP])
    return row, None


ARROW_TYPES = {
    "VARCHAR": pa.string(),
    "BIGINT": pa.int64(),
    "TIMESTAMPTZ": pa.timestamp("us", tz="UTC"),
    "BOOLEAN": pa.bool_(),
    "DOUBLE": pa.float64(),
}
TIMESTAMP = ARROW_TYPES["TIMESTAMPTZ"]

REQUEST_LOG_SCHEMA = pa.schema(
    [pa.field(column, ARROW_TYPES[kind]) for column, kind, _ in FIELDS] + [
        pa.field("object_key", pa.string()),
        pa.field("line_no", pa.int64()),
        pa.field("ingested_at", TIMESTAMP),
    ])


@dataclass(frozen=True)
class Split:
    """The accepted request_log table, and the failed lines as the input table's ``row`` ordinals."""

    accepted: pa.Table
    failed_rows: list[int]
    failed_reasons: list[str]


def split(table: pa.Table, ingested_at: dt.datetime) -> Split:
    """The unit's lines as ``REQUEST_LOG_SCHEMA``, keeping the first of each ``ray_id``; the rest failed.

    The Source (``CsvObjectSource`` reading one column) has only cut the object into lines. Everything about a
    line being JSON, an object, keyed and typed is judged here.
    """
    needed = [ROW, OBJECT_KEY_COLUMN, LINE_NO_COLUMN, LINE]
    missing = [c for c in needed if c not in table.column_names]
    if missing:
        raise TypeError("s3_gzip: the unit table lacks the column(s) %s" % ", ".join(missing))

    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    failed_rows: list[int] = []
    failed_reasons: list[str] = []
    for ordinal, key, line_no, line in zip(*(table.column(c).to_pylist() for c in needed)):
        if line is None or not line.strip():
            row, reason = None, BLANK_LINE
        else:
            row, reason = parse_line(line.encode())
        if row is not None and row["ray_id"] in seen:
            row, reason = None, DUPLICATE_IN_OBJECT
        if row is None:
            failed_rows.append(ordinal)
            failed_reasons.append(reason)
            continue
        seen.add(row["ray_id"])
        row.update(object_key=str(key), line_no=int(line_no), ingested_at=ingested_at)
        rows.append(row)
    arrays = [pa.array([r[f.name] for r in rows], f.type) for f in REQUEST_LOG_SCHEMA]
    return Split(pa.Table.from_arrays(arrays, schema=REQUEST_LOG_SCHEMA), failed_rows, failed_reasons)
