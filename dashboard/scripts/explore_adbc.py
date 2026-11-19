#!/usr/bin/env python3
"""Explore via Overview → ADBC (Python). Same Quack endpoint / TOKEN as DuckDB ATTACH."""

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

from quack_auth import normalize_host, quack_token


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--host",
        default=os.getenv("ADS_QUERY_HOST")
        or "ads-cloudflare-poc-k9pb59-tor1.aidp-preview.ondigitalocean.com:443",
    )
    p.add_argument("--token", default="")
    p.add_argument(
        "--table",
        default=os.getenv("ADS_TABLE", "tabular.ads_cloudflare_poc.cf_request_log"),
    )
    p.add_argument("--sql", default="")
    args = p.parse_args()

    host = normalize_host(args.host)
    token = quack_token(args.token or None)
    if not token:
        print("Set ADS_QUACK_TOKEN=reader:<password> in .env", file=sys.stderr)
        return 2

    from adbc_driver_quack import dbapi as quack

    sql = args.sql.strip() or f"""
SELECT count(*) AS rows
FROM {args.table}
WHERE edge_start_timestamp >= TIMESTAMP '2026-11-10 14:30:00 UTC'
  AND edge_start_timestamp <  TIMESTAMP '2026-11-10 14:31:00 UTC'
""".strip()

    print(f"ADBC quack://{host}")
    try:
        with quack.connect(
            uri=f"quack://{host}",
            db_kwargs={
                "adbc.quack.token": token,
                "adbc.quack.tls": "true",
                "adbc.quack.rpc.timeout_seconds.request": "180",
            },
        ) as conn, conn.cursor() as cur:
            cur.execute(sql)
            table = cur.fetch_arrow_table()
    except Exception as e:
        print(f"Connect/query failed: {e}", file=sys.stderr)
        return 1

    print(table)
    try:
        print(table.to_pandas().to_string(index=False))
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
