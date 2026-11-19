# CF Edge Log Dashboard

Public App Platform PoC: charts over ADS Iceberg table `cf_request_log` (data flow `cf-http-logs-poc`).

**What each panel means and which rows it uses:** see **[DASHBOARD.md](./DASHBOARD.md)**.

## Stack

- FastAPI + static UI
- ADS Query API: `POST https://$ADS_QUERY_HOST/query` + `DIGITALOCEAN_TOKEN`
- Disk/memory aggregate cache (default 30 minutes)

## Local run

```bash
cd dashboard
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # set DIGITALOCEAN_TOKEN + ADS_QUERY_HOST
uvicorn app.main:app --reload --port 8080
```

Open http://127.0.0.1:8080 — start with **1 minute** or **Fast sample**.

## App Platform (TOR1)

Source directory: `dashboard`. Set secrets `ADS_QUERY_HOST`, `DIGITALOCEAN_TOKEN`, and `ADS_TABLE=tabular.ads_cloudflare_poc.cf_request_log`. See `app.yaml`.

## Optional: DuckDB / ADBC explore

Overview → DuckDB Python uses `TOKEN 'reader:<password>'` (not the HTTP PAT). Python 3.11+ and DuckDB 2.x required.

```bash
python3.11 -m venv .venv-explore && source .venv-explore/bin/activate
pip install -r requirements-explore.txt
# ADS_QUACK_TOKEN=reader:… in .env
python scripts/explore_duckdb.py
```

More detail: [notebooks/explore_ads.md](./notebooks/explore_ads.md).

## Notes

- Never commit `.env`.
- Clear cache: `POST /api/cache/clear`
