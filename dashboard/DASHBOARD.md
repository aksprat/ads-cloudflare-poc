# Edge Log Intelligence — dashboard guide

Live UI over Cloudflare HTTP logs landed in ADS by data flow **`cf-http-logs-poc`**.

## What it queries

| Item | Value |
|------|--------|
| Workspace | `ads-cloudflare-poc` (tor1) |
| Table | `tabular.ads_cloudflare_poc.cf_request_log` |
| Grain | **One row per HTTP request** (Iceberg, ~33 hot-path columns) |
| Typical volume | ~1.6B rows / day in the PoC backfill; ~1M+ / minute |

The app does **not** read S3 directly. It runs DuckDB SQL through ADS **`POST /query`** with a workspace PAT, aggregates in ADS, and caches JSON results (memory + `dashboard/.cache/`).

**Filters every panel shares**

- Optional time window (`start` / `end` on `edge_start_timestamp`)
- Optional **fast sample**: `date_part('minute', edge_start_timestamp) = 30` (~1 minute per hour)

Client types (browser, SDK, crawler, AI/MCP, …) are derived in SQL from `client_request_user_agent` (same idea as `handoff/scripts/day.py`).

## How it is built

```text
Browser (static/)  →  FastAPI (app/)  →  ADS Query API  →  Iceberg cf_request_log
                         ↑ cache
```

| Piece | Role |
|-------|------|
| `static/` | Single-page UI; loads each panel via its own `/api/…` call (max 2 concurrent) |
| `app/queries.py` | DuckDB SQL for each panel |
| `app/service.py` | Runs queries, TTL cache, concurrency limit |
| `app/ads.py` | `POST https://$ADS_QUERY_HOST/query` |
| `Dockerfile` / `app.yaml` | App Platform (TOR1) |

## Sections (what you see)

### Ingest health
Row count and min/max `edge_start_timestamp` / `ingested_at` for the window. Confirms the slice the other charts use.

### Overview · client mix
- **Client classes** — non-OTLP rows only, grouped by UA taxonomy.
- **Hourly shape** — stacked browser / SDK / HTTP lib / AI / crawler (+ API 401/429 & MCP counts in the same hourly query).
- **Top hosts** — `client_request_host` volume, 5xx, avg TTFB.

### C · Auth friction
Errors on **`api.digitalocean.com`** with status in (401, 429, 403, 404, 5xx). Paths normalized (IDs → `{id}`, zones → `{zone}`).

### B · MCP adoption
Rows for **`mcp.digitalocean.com`**. Breakdown by client family (Cursor, Codex, Claude, …), 2xx / 401 / 404. Treat **401 as OAuth challenge**, not necessarily failure.

### D · Regions & edge latency
- Top `client_country` counts (all hosts in window).
- p50/p95 TTFB by `edge_colo_code` for **api** and **cloud** hosts.

### H · Telemetry fleet
Hosts starting with **`otlp-`** (majority of all rows). Volume, non-200, avg/p95 TTFB by OTLP region.

### K · Cost to serve
GET HTML (or null content-type) on **www** / **docs**. Bytes, origin ms, and “bypass-ish” cache share by client type.

### N · Reliability watch
Non-OTLP rows with **status ≥ 500**, by host, plus `security_action` in (`block`, `challenge`).

## Why first load is slow

Iceberg holds **raw requests**. Each cold panel scans millions of rows. Second load uses cache (~30 min). Long-term speed needs **rollup tables**, not a different connection client.
