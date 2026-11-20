#!/usr/bin/env python3
"""Explore cf_request_log via Overview → DuckDB Python (quack: ATTACH).

Matches the Control Panel snippet::

    ATTACH 'quack:<host>:443' AS srv (TOKEN 'reader:<password>')
    SELECT * FROM srv.tabular.<schema>.<table> LIMIT 10

This is for laptop / notebook exploration. The App Platform dashboard uses the
same Quack engine via ADBC (``app/ads.py``).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass

import duckdb
from quack_auth import normalize_host, quack_token, table_fqn


def connect(host: str, token: str, alias: str = "srv"):
    if duckdb.__version__.startswith("1."):
        raise SystemExit(
            f"DuckDB {duckdb.__version__} only has the stub quack() extension.\n"
            "Use Python 3.11+ and duckdb>=2.0 (see requirements-explore.txt)."
        )
    con = duckdb.connect()
    con.execute("INSTALL quack; LOAD quack;")
    con.execute(f"ATTACH 'quack:{host}' AS {alias} (TOKEN '{token}')")
    return con


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--host",
        default=os.getenv("ADS_QUERY_HOST")
        or "ads-cloudflare-poc-k9pb59-tor1.aidp-preview.ondigitalocean.com:443",
    )
    p.add_argument(
        "--token",
        default="",
        help="Overview TOKEN value, e.g. reader:<password> (or set ADS_QUACK_TOKEN)",
    )
    p.add_argument(
        "--table",
        default=os.getenv("ADS_TABLE", "tabular.ads_cloudflare_poc.cf_request_log"),
        help="Catalog path as in HTTP API (tabular.schema.table)",
    )
    p.add_argument("--sql", default="", help="SQL; use view alias `logs`")
    args = p.parse_args()

    host = normalize_host(args.host)
    token = quack_token(args.token or None)
    if not token:
        print(
            "Set ADS_QUACK_TOKEN=reader:<password> in .env\n"
            "(same string as Overview → DuckDB Python → TOKEN '...').",
            file=sys.stderr,
        )
        return 2

    print(f"DuckDB {duckdb.__version__}")
    print(f"ATTACH quack:{host} AS srv (TOKEN 'reader:***')")
    try:
        con = connect(host, token)
    except Exception as e:
        print(f"ATTACH failed: {e}", file=sys.stderr)
        return 1

    fqn = table_fqn(args.table, for_attach_alias="srv")
    con.execute(f"CREATE OR REPLACE VIEW logs AS SELECT * FROM {fqn}")
    print("Databases:", con.execute("SHOW DATABASES").fetchall())
    print(f"View `logs` → {fqn}")

    # Default is a light LIMIT probe (aggregates can HTTP 524 on cold scans).
    sql = args.sql.strip() or """
SELECT
  ray_id,
  edge_start_timestamp,
  client_request_host,
  edge_response_status
FROM logs
WHERE edge_start_timestamp >= TIMESTAMP '2026-11-10 14:30:00 UTC'
  AND edge_start_timestamp <  TIMESTAMP '2026-11-10 14:31:00 UTC'
LIMIT 5
""".strip()

    print("\nSQL:\n", sql, "\n", sep="")
    try:
        print(con.execute(sql).df().to_string(index=False))
    except Exception as e:
        print(f"Query failed: {e}", file=sys.stderr)
        print("Heavy aggregates can HTTP 524; retry or narrow the time window.", file=sys.stderr)
        return 1
    return 0



if __name__ == "__main__":
    raise SystemExit(main())
