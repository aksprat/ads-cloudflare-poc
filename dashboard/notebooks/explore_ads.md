# Explore ADS with DuckDB Python

Use this for notebook-style SQL against `cf_request_log`.  
The hosted dashboard uses the same Quack path via **ADBC** (`app/ads.py`).

## Overview snippet (works)

```python
import duckdb

con = duckdb.connect()
con.execute(
    "ATTACH 'quack:ads-cloudflare-poc-k9pb59-tor1.aidp-preview.ondigitalocean.com:443' "
    "AS srv (TOKEN 'reader:<PASSWORD>')"
)
print(
    con.execute(
        "SELECT * FROM srv.tabular.ads_cloudflare_poc.cf_request_log LIMIT 10"
    ).fetchall()
)
```

Important details:

- **TOKEN** is `reader:<password>` (user and password together), not the bare password and not the `doo_v1_…` PAT.
- Table path after ATTACH: `srv.tabular.ads_cloudflare_poc.cf_request_log` (same `tabular.…` FQN as Semantic Query / HTTP API, prefixed with `srv.`).

## Env setup

```env
ADS_QUERY_HOST=ads-cloudflare-poc-k9pb59-tor1.aidp-preview.ondigitalocean.com:443
ADS_QUACK_TOKEN=reader:your_password_here
ADS_TABLE=tabular.ads_cloudflare_poc.cf_request_log
```

## Install (Python 3.11+)

```bash
cd dashboard
python3.11 -m venv .venv-explore
source .venv-explore/bin/activate
pip install -r requirements-explore.txt
```

DuckDB **2.x** is required (1.4’s `quack` is a stub).

## Run helpers

```bash
python scripts/explore_duckdb.py
python scripts/explore_adbc.py

python scripts/explore_duckdb.py --sql \
  "SELECT client_request_host, count(*) n FROM logs GROUP BY 1 ORDER BY n DESC LIMIT 10"
```

## Speed note

A one-minute `count(*)` over Quack was ~21s here — same ballpark as HTTP `/query`.  
DuckDB/ADBC help for **pandas/Arrow and local joins**, not for making raw Iceberg scans fast.
