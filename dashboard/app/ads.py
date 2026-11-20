"""ADS Query Engine client via ADBC Quack (not the HTTP /query UI API)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

from .config import Settings
from .quack_auth import normalize_host, quack_token

log = logging.getLogger("dashboard.ads")


class AdsQueryError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def _connect(settings: Settings):
    token = quack_token(settings.ads_quack_token or None)
    if not token:
        raise AdsQueryError(
            "ADS_QUACK_TOKEN is not set (expected Overview TOKEN 'reader:<password>')"
        )

    host = normalize_host(settings.ads_query_host)
    try:
        from adbc_driver_quack import dbapi as quack
    except ImportError as e:
        raise AdsQueryError(
            "adbc-driver-quack is not installed; add it to requirements.txt"
        ) from e

    return quack.connect(
        uri=f"quack://{host}",
        db_kwargs={
            "adbc.quack.token": token,
            "adbc.quack.tls": "true",
            "adbc.quack.rpc.timeout_seconds.request": str(settings.ads_timeout_seconds),
        },
    )


def _arrow_to_rows(table) -> list[dict[str, Any]]:
    """Convert an Arrow table to JSON-friendly list[dict]."""
    # Prefer column iteration to avoid a pandas dependency at runtime.
    names = table.column_names
    n = table.num_rows
    cols = [table.column(i).to_pylist() for i in range(table.num_columns)]
    rows: list[dict[str, Any]] = []
    for i in range(n):
        row = {}
        for j, name in enumerate(names):
            v = cols[j][i]
            # Timestamps / decimals → str for JSON
            if hasattr(v, "isoformat"):
                v = v.isoformat()
            elif hasattr(v, "as_py"):
                v = v.as_py()
            row[name] = v
        rows.append(row)
    return rows


def _run_sql_sync(settings: Settings, sql: str, max_rows: int = 500) -> dict[str, Any]:
    limited = sql.rstrip().rstrip(";")
    # Safety cap for accidental wide selects; aggregate panels already LIMIT.
    if " limit " not in limited.lower():
        limited = f"{limited}\nLIMIT {max_rows}"

    t0 = time.perf_counter()
    try:
        with _connect(settings) as conn, conn.cursor() as cur:
            cur.execute(limited)
            table = cur.fetch_arrow_table()
    except AdsQueryError:
        raise
    except Exception as e:
        raise AdsQueryError(f"ADBC Quack query failed: {e}", body=str(e)[:2000]) from e

    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    rows = _arrow_to_rows(table)
    truncated = len(rows) >= max_rows and " limit " not in sql.lower()
    log.info(
        "quack ok rows=%s truncated=%s elapsed_ms=%s",
        len(rows),
        truncated,
        elapsed_ms,
    )
    return {
        "rows": rows,
        "rowCount": len(rows),
        "elapsedMs": elapsed_ms,
        "truncated": truncated,
    }


async def run_sql(settings: Settings, sql: str, max_rows: int = 500) -> dict[str, Any]:
    """Run DuckDB-dialect SQL on the Quack query engine (thread offload)."""
    return await asyncio.to_thread(_run_sql_sync, settings, sql, max_rows)


def rows_as_dicts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Compatibility helper — payload already holds list[dict] under ``rows``."""
    rows = payload.get("rows") or []
    if rows and isinstance(rows[0], dict):
        return rows
    # Legacy HTTP shape: columns + row arrays
    cols = [c["name"] if isinstance(c, dict) else c for c in (payload.get("columns") or [])]
    return [dict(zip(cols, row)) for row in rows]
