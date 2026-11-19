# ads-cloudflare-poc

PoC: Cloudflare Logpush (S3) → DigitalOcean **Agent Data Services** → queryable Iceberg → **edge log dashboard**.

## What’s in this repo

| Path | Purpose |
|------|---------|
| [`dashboard/`](./dashboard/) | FastAPI + UI on App Platform; queries live ADS data |
| [`dashboard/DASHBOARD.md`](./dashboard/DASHBOARD.md) | What each dashboard section shows and which rows it uses |
| [`handoff/`](./handoff/) | Offline analysis + mock UI that defined the product panels |
| [`cf-http-logs-flow/`](./cf-http-logs-flow/) | Data-flow project (S3 gzip NDJSON → `cf_request_log`) |
| [`PLAYBOOK-cloudflare-ads-poc.md`](./PLAYBOOK-cloudflare-ads-poc.md) | End-to-end ingest playbook |
| `cloudflare_*.sql` | Schema / DDL sketches |

## Dashboard (short)

- **Source table:** `tabular.ads_cloudflare_poc.cf_request_log` (one row per HTTP request).
- **How:** browser → FastAPI → ADS `POST /query` → aggregates → cached JSON → charts.
- **Panels:** ingest, client mix, API auth errors, MCP, regions/latency, OTLP, cost-to-serve, reliability.

Full walkthrough: **[dashboard/DASHBOARD.md](./dashboard/DASHBOARD.md)**.  
Run / deploy: **[dashboard/README.md](./dashboard/README.md)**.

## Quick start (dashboard)

```bash
cd dashboard
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # DIGITALOCEAN_TOKEN with ads_query + ADS_QUERY_HOST
uvicorn app.main:app --reload --port 8080
```

## ADS pointers

- Workspace: `ads-cloudflare-poc` · region `tor1`
- Data flow: `cf-http-logs-poc`
- Do not commit `.env` or tokens
