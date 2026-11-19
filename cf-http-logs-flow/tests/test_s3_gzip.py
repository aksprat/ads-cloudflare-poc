"""The entry against testdata/*.log.gz, with stand-ins for the runtime's CsvObjectSource and aidc_runtime.

Run from the project folder: ``python3 -m unittest discover -s tests`` (needs pyarrow).
"""

from __future__ import annotations

import datetime as dt
import gzip
import re
import sys
import types
import unittest
from pathlib import Path

import pyarrow as pa

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _failed_table(rows: list[int], reasons: list[str]) -> pa.Table:
    return pa.table({"row": pa.array(rows, pa.int64()), "failed_reason": pa.array(reasons, pa.string())})


# aidc_runtime ships in the guest, not on PyPI: only failed_table is used.
sys.modules.setdefault("aidc_runtime", types.SimpleNamespace(failed_table=_failed_table))

from s3_gzip import logs, pipeline  # noqa: E402

PACKAGE = Path(pipeline.__file__).parent
CLOCK = dt.datetime(2026, 11, 16, 12, 0, 0, 123456, tzinfo=dt.timezone.utc)
AUTHOR_REASON = re.compile(r"^author\.[a-z0-9_.-]{1,64}$")


class FakeBatch:
    """What the entry reads from a runtime Batch: ``table()``."""

    def __init__(self, table: pa.Table) -> None:
        self._table = table

    def table(self) -> pa.Table:
        return self._table


def read_unit(data: bytes, key: str) -> FakeBatch:
    """The object as the runtime hands it over: decompressed (by magic), then cut into one-column rows by ``CsvObjectSource``.

    The unit table is ``row`` (int64), the ``source.ddl`` column ``line``, then ``source_ref`` and ``source_offset``
    (the 0-based line number, no header). The Source cuts at ``\\n`` and drops the terminator and the final empty row.
    """
    plain = gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data
    lines = plain.decode().split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    n = len(lines)
    return FakeBatch(pa.table({
        logs.ROW: pa.array(range(n), pa.int64()),
        logs.LINE: pa.array(lines, pa.string()),
        logs.OBJECT_KEY_COLUMN: pa.array([key] * n, pa.string()),
        logs.LINE_NO_COLUMN: pa.array(range(n), pa.int64()),
    }))


def entry() -> pipeline.Entry:
    e = pipeline.Entry()
    e.clock = lambda: CLOCK
    return e


def run(name: str) -> tuple[pa.Table, pa.Table | None]:
    return entry()(read_unit((ROOT / "testdata" / name).read_bytes(), "logs/" + name))


class SinkDdl(unittest.TestCase):
    def test_sink_ddl_matches_the_entry(self) -> None:
        ddl = (PACKAGE / "sink.ddl").read_text()
        self.assertIn("CREATE TABLE IF NOT EXISTS %s (" % pipeline.Entry.table, ddl)
        columns = re.findall(r"^    (\w+) (\w+),?$", ddl, re.M)
        expected = [(c, t) for c, t, _ in logs.FIELDS] + [
            ("object_key", "VARCHAR"), ("line_no", "BIGINT"), ("ingested_at", "TIMESTAMPTZ")]
        self.assertEqual(columns, expected)
        self.assertEqual(len(logs.FIELDS), 33)

    def test_source_ddl_is_one_line_column(self) -> None:
        self.assertEqual(re.findall(r"^    (\w+) (\w+)", (PACKAGE / "source.ddl").read_text(), re.M), [("line", "VARCHAR")])

    def test_manifest_cuts_lines_on_a_byte_json_never_holds(self) -> None:
        import tomllib
        manifest = tomllib.loads((ROOT / "data-flow.toml").read_text())
        options = manifest["runtime"]["source"]["options"]
        self.assertEqual(manifest["runtime"]["source"]["class"], "aidc_runtime.sources:CsvObjectSource")
        self.assertEqual((options["has_header"], options["delimiter"]), ("false", "\x01"))


class CleanObject(unittest.TestCase):
    def test_every_line_is_accepted_and_nothing_fails(self) -> None:
        accepted, failed = run("requests_clean.log.gz")
        self.assertEqual(accepted.num_rows, 6)
        self.assertIsNone(failed)
        self.assertEqual(accepted.schema, logs.REQUEST_LOG_SCHEMA)

    def test_provenance_and_ingest_time(self) -> None:
        accepted, _ = run("requests_clean.log.gz")
        self.assertEqual(set(accepted.column("object_key").to_pylist()), {"logs/requests_clean.log.gz"})
        self.assertEqual(accepted.column("line_no").to_pylist(), [0, 1, 2, 3, 4, 5])
        self.assertEqual(set(accepted.column("ingested_at").to_pylist()), {CLOCK})

    def test_types_come_through(self) -> None:
        row = run("requests_clean.log.gz")[0].slice(0, 1).to_pylist()[0]
        self.assertEqual(row["ray_id"], "ray0001")
        self.assertEqual(row["edge_start_timestamp"], dt.datetime(2026, 11, 10, 0, 0, 1, tzinfo=dt.timezone.utc))
        self.assertEqual(row["client_asn"], 14061)
        self.assertEqual(row["client_request_bytes"], 301)

    def test_client_ip_is_hashed_and_empty_origin_ip_is_null(self) -> None:
        row = run("requests_clean.log.gz")[0].slice(0, 1).to_pylist()[0]
        self.assertEqual(row["client_ip"], logs.hash_ip("203.0.113.1"))
        self.assertNotIn("203.0.113", row["client_ip"])
        self.assertIsNone(row["origin_ip"])

    def test_a_plain_object_is_the_same(self) -> None:
        plain = gzip.decompress((ROOT / "testdata" / "requests_clean.log.gz").read_bytes())
        accepted, failed = entry()(read_unit(plain, "logs/requests_clean.log"))
        self.assertEqual((accepted.num_rows, failed), (6, None))


class ObjectWithErrors(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.accepted, cls.failed = run("requests_with_errors.log.gz")

    def test_good_lines_are_accepted_in_order(self) -> None:
        self.assertEqual(self.accepted.column("ray_id").to_pylist(), ["ray0001", "ray0002", "ray0003", "ray0004"])
        self.assertEqual(self.accepted.column("line_no").to_pylist(), [0, 1, 2, 3])

    def test_each_bad_line_fails_for_its_own_reason(self) -> None:
        reasons = dict(zip(self.failed.column("row").to_pylist(), self.failed.column("failed_reason").to_pylist()))
        self.assertEqual(reasons, {
            4: logs.MALFORMED_JSON, 5: logs.NOT_AN_OBJECT, 6: logs.MISSING_RAY_ID, 7: logs.DUPLICATE_IN_OBJECT,
            8: "author.bad_value.edge_response_status"})

    def test_failed_reasons_are_author_slugs(self) -> None:
        for reason in self.failed.column("failed_reason").to_pylist():
            self.assertRegex(reason, AUTHOR_REASON)

    def test_failed_table_shape(self) -> None:
        self.assertEqual(self.failed.schema.names, ["row", "failed_reason"])
        self.assertEqual(self.failed.schema.field("row").type, pa.int64())

    def test_every_input_row_is_accepted_or_failed_once(self) -> None:
        self.assertEqual(self.accepted.num_rows + self.failed.num_rows, 9)


class OddInput(unittest.TestCase):
    def test_a_blank_line_fails(self) -> None:
        batch = read_unit(b'{"RayID": "r1", "EdgeStartTimestamp": "2026-11-10T00:00:00Z"}\n\n', "logs/x.log")
        accepted, failed = entry()(batch)
        self.assertEqual(accepted.num_rows, 1)
        self.assertEqual(failed.column("failed_reason").to_pylist(), [logs.BLANK_LINE])

    def test_a_missing_timestamp_fails(self) -> None:
        accepted, failed = entry()(read_unit(b'{"RayID": "r1"}\n', "logs/x.log"))
        self.assertEqual(accepted.num_rows, 0)
        self.assertEqual(failed.column("failed_reason").to_pylist(), ["author.bad_value.edge_start_timestamp"])

    def test_epoch_timestamps_are_read(self) -> None:
        accepted, _ = entry()(read_unit(b'{"RayID": "r1", "EdgeStartTimestamp": 1794787201}\n', "logs/x.log"))
        self.assertEqual(accepted.column("edge_start_timestamp")[0].as_py().year, 2026)

    def test_a_number_outside_int64_fails_the_line_not_the_unit(self) -> None:
        good = b'{"RayID": "r2", "EdgeStartTimestamp": "2026-11-10T00:00:00Z"}'
        big = b'{"RayID": "r1", "EdgeStartTimestamp": "2026-11-10T00:00:00Z", "ClientASN": %d}' % 2**70
        accepted, failed = entry()(read_unit(big + b"\n" + good + b"\n", "logs/x.log"))
        self.assertEqual(accepted.column("ray_id").to_pylist(), ["r2"])
        self.assertEqual(failed.column("failed_reason").to_pylist(), ["author.bad_value.client_asn"])

    def test_a_fraction_is_not_cut_to_a_whole_number(self) -> None:
        row, reason = logs.parse_line(b'{"RayID": "r", "EdgeStartTimestamp": "2026-11-10T00:00:00Z", "ClientASN": 1.9}')
        self.assertEqual((row, reason), (None, "author.bad_value.client_asn"))
        row, _ = logs.parse_line(b'{"RayID": "r", "EdgeStartTimestamp": "2026-11-10T00:00:00Z", "ClientASN": 7.0}')
        self.assertEqual(row["client_asn"], 7)

    def test_arrays_objects_and_booleans_in_text_columns_become_json_text(self) -> None:
        row, _ = logs.parse_line(b'{"RayID": "r", "EdgeStartTimestamp": "2026-11-10T00:00:00Z", '
                                 b'"ZoneName": true, "SecurityAction": ["a", "b"], "ClientCountry": {"x": 1}}')
        self.assertEqual((row["zone_name"], row["security_action"], row["client_country"]), ("true", '["a","b"]', '{"x":1}'))

    def test_nanosecond_and_offset_timestamps_are_read(self) -> None:
        for stamp in ("2026-11-10T00:00:01.123456789Z", "2026-11-10T00:00:01+00:00"):
            row, reason = logs.parse_line(('{"RayID": "r", "EdgeStartTimestamp": "%s"}' % stamp).encode())
            self.assertIsNone(reason, stamp)
            self.assertEqual(row["edge_start_timestamp"].second, 1)

    def test_manifest_json_matches_the_toml(self) -> None:
        import json
        import tomllib
        self.assertEqual(json.loads((ROOT / "manifest.src.json").read_text()),
                         tomllib.loads((ROOT / "data-flow.toml").read_text()))

    def test_a_unit_without_the_source_columns_is_refused(self) -> None:
        with self.assertRaises(TypeError):
            entry()(FakeBatch(pa.table({"row": pa.array([0], pa.int64())})))


if __name__ == "__main__":
    unittest.main()
