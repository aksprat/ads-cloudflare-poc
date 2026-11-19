#!/usr/bin/env python3
"""Same exploratory queries as explore_duckdb.py, via HTTP POST /query.

Works today with DIGITALOCEAN_TOKEN (ads_query) — no Quack token required.
Useful when DuckDB ATTACH auth is not set up yet, or for App Platform parity.

Usage (from dashboard/, with .env filled):
  .venv/bin/python scripts/explore_http.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from app.ads import rows_as_dicts, run_sql
from app.config import get_settings


async def main() -> None:
    settings = get_settings()
    table = settings.ads_table
    window = """
      edge_start_timestamp >= TIMESTAMP '2026-11-10 14:30:00 UTC'
      AND edge_start_timestamp <  TIMESTAMP '2026-11-10 14:31:00 UTC'
    """
    queries = {
        "coverage": f"""
            SELECT count(*) AS rows,
                   min(edge_start_timestamp) AS t_min,
                   max(edge_start_timestamp) AS t_max
            FROM {table}
            WHERE {window}
        """,
        "top_hosts": f"""
            SELECT split_part(client_request_host, ':', 1) AS host, count(*) AS n
            FROM {table}
            WHERE {window}
            GROUP BY 1
            ORDER BY n DESC
            LIMIT 10
        """,
    }
    for name, sql in queries.items():
        print(f"\n=== {name} ===")
        payload = await run_sql(settings, sql.strip(), max_rows=50)
        print(f"elapsed_ms={payload.get('elapsedMs')}")
        for row in rows_as_dicts(payload):
            print(row)


if __name__ == "__main__":
    if not os.environ.get("DIGITALOCEAN_TOKEN"):
        raise SystemExit("Set DIGITALOCEAN_TOKEN in dashboard/.env")
    asyncio.run(main())
