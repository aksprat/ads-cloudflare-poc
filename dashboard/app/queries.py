"""SQL for MVP panels against the 33-column cf_request_log table (DuckDB dialect).

Iceberg holds raw request rows. These queries aggregate at read time.
`sample=True` keeps one minute per hour (minute == 30), matching the handoff
method — typically ~60x less data than a full hour window.
"""

from __future__ import annotations

# Strip :443 from Logpush hosts.
HOST = "split_part(client_request_host, ':', 1)"
UA = "coalesce(client_request_user_agent, '')"

# Cheaper than a giant regexp_matches: ILIKE short-circuits and mirrors day.py order.
CLIENT_CLASS = f"""
CASE
  WHEN {UA} = '' THEN 'empty'
  WHEN (
      {UA} ILIKE '%bot%' OR {UA} ILIKE '%spider%' OR {UA} ILIKE '%crawl%'
      OR {UA} ILIKE '%GPTBot%' OR {UA} ILIKE '%ClaudeBot%' OR {UA} ILIKE '%Bytespider%'
      OR {UA} ILIKE '%Perplexity%' OR {UA} ILIKE '%Amazonbot%' OR {UA} ILIKE '%bingbot%'
      OR {UA} ILIKE '%Googlebot%' OR {UA} ILIKE '%Uptime%' OR {UA} ILIKE '%Pingdom%'
    )
    AND {UA} NOT ILIKE '%do-agent%' AND {UA} NOT ILIKE '%mongo-agent%' AND {UA} NOT ILIKE '%ha-agent%'
    THEN 'crawler'
  WHEN starts_with({UA}, 'Mozilla') THEN 'browser'
  WHEN (
      {UA} ILIKE '%claude%' OR {UA} ILIKE '%anthropic%' OR {UA} ILIKE '%openai%'
      OR {UA} ILIKE '%chatgpt%' OR {UA} ILIKE '%codex%' OR {UA} ILIKE '%copilot%'
      OR {UA} ILIKE '%cursor%' OR {UA} ILIKE '%mcp%' OR {UA} ILIKE '%gemini%'
      OR {UA} ILIKE '%perplexity%' OR {UA} ILIKE '%langchain%'
    )
    AND {UA} NOT ILIKE '%do-agent%' AND {UA} NOT ILIKE '%mongo-agent%' AND {UA} NOT ILIKE '%ha-agent%'
    THEN 'ai_client'
  WHEN (
      {UA} ILIKE '%godo%' OR {UA} ILIKE '%doctl%' OR {UA} ILIKE '%terraform%'
      OR {UA} ILIKE '%pulumi%' OR {UA} ILIKE '%ansible%' OR {UA} ILIKE '%do-agent%'
      OR {UA} ILIKE '%cert-manager%' OR {UA} ILIKE '%kubectl%' OR {UA} ILIKE '%helm%'
      OR {UA} ILIKE '%external-dns%' OR {UA} ILIKE '%csi-digitalocean%'
    )
    THEN 'sdk_infra'
  WHEN (
      {UA} ILIKE 'node%' OR {UA} ILIKE 'go-http%' OR {UA} ILIKE 'python%'
      OR {UA} ILIKE '%axios%' OR {UA} ILIKE '%httpx%' OR {UA} ILIKE 'curl%'
      OR {UA} ILIKE 'Bun%' OR {UA} ILIKE '%okhttp%' OR {UA} ILIKE '%undici%'
      OR {UA} ILIKE 'wget%' OR {UA} ILIKE '%reqwest%'
    )
    THEN 'http_lib'
  ELSE 'other'
END
"""

IS_OTLP = f"starts_with({HOST}, 'otlp-')"
IS_API = f"{HOST} = 'api.digitalocean.com'"
IS_MCP = f"{HOST} = 'mcp.digitalocean.com'"
IS_WWW_DOCS = f"{HOST} IN ('www.digitalocean.com', 'docs.digitalocean.com')"


def _window(start: str | None, end: str | None, sample: bool = False) -> str:
    clauses = []
    if start:
        clauses.append(f"edge_start_timestamp >= TIMESTAMP '{start}'")
    if end:
        clauses.append(f"edge_start_timestamp < TIMESTAMP '{end}'")
    if sample:
        # One minute per hour — same idea as the handoff 25-file sample.
        clauses.append("date_part('minute', edge_start_timestamp) = 30")
    return (" WHERE " + " AND ".join(clauses)) if clauses else ""


def coverage_sql(table: str, start: str | None = None, end: str | None = None, sample: bool = False) -> str:
    # Skip count(DISTINCT object_key) — expensive and not needed for KPIs.
    return f"""
SELECT
  count(*) AS rows,
  min(edge_start_timestamp) AS t_min,
  max(edge_start_timestamp) AS t_max,
  min(ingested_at) AS ingest_min,
  max(ingested_at) AS ingest_max
FROM {table}
{_window(start, end, sample)}
""".strip()


def overview_sql(table: str, start: str | None = None, end: str | None = None, sample: bool = False) -> str:
    w = _window(start, end, sample)
    where = w + (" AND " if w else " WHERE ") + f"NOT ({IS_OTLP})"
    return f"""
SELECT
  {CLIENT_CLASS} AS client_class,
  count(*) AS requests
FROM {table}
{where}
GROUP BY 1
ORDER BY requests DESC
""".strip()


def hourly_mix_sql(table: str, start: str | None = None, end: str | None = None, sample: bool = False) -> str:
    """Classify once in a CTE, then aggregate — avoids re-evaluating CLIENT_CLASS 5×."""
    w = _window(start, end, sample)
    return f"""
WITH base AS (
  SELECT
    date_trunc('hour', edge_start_timestamp) AS hour,
    {IS_OTLP} AS is_otlp,
    {IS_API} AS is_api,
    {IS_MCP} AS is_mcp,
    {HOST} AS host,
    edge_response_status AS status,
    CASE WHEN NOT ({IS_OTLP}) THEN ({CLIENT_CLASS}) ELSE NULL END AS client_class
  FROM {table}
  {w}
)
SELECT
  hour,
  count(*) AS requests,
  sum(CASE WHEN is_otlp THEN 1 ELSE 0 END) AS telemetry,
  sum(CASE WHEN client_class = 'browser' THEN 1 ELSE 0 END) AS browser,
  sum(CASE WHEN client_class = 'sdk_infra' THEN 1 ELSE 0 END) AS sdk_infra,
  sum(CASE WHEN client_class = 'http_lib' THEN 1 ELSE 0 END) AS http_lib,
  sum(CASE WHEN client_class = 'ai_client' THEN 1 ELSE 0 END) AS ai_client,
  sum(CASE WHEN client_class = 'crawler' THEN 1 ELSE 0 END) AS crawler,
  sum(CASE WHEN is_api THEN 1 ELSE 0 END) AS api_total,
  sum(CASE WHEN is_api AND status = 401 THEN 1 ELSE 0 END) AS api_401,
  sum(CASE WHEN is_api AND status = 429 THEN 1 ELSE 0 END) AS api_429,
  sum(CASE WHEN is_mcp THEN 1 ELSE 0 END) AS mcp,
  sum(CASE WHEN host = 'logging.digitalocean.com' AND status >= 500 THEN 1 ELSE 0 END) AS logging_5xx
FROM base
GROUP BY 1
ORDER BY 1
""".strip()


def top_hosts_sql(table: str, start: str | None = None, end: str | None = None, sample: bool = False, limit: int = 15) -> str:
    w = _window(start, end, sample)
    return f"""
SELECT
  {HOST} AS host,
  count(*) AS requests,
  sum(CASE WHEN edge_response_status >= 500 THEN 1 ELSE 0 END) AS s5xx,
  round(avg(edge_time_to_first_byte_ms), 1) AS avg_ttfb_ms
FROM {table}
{w}
GROUP BY 1
ORDER BY requests DESC
LIMIT {limit}
""".strip()


def api_errors_sql(table: str, start: str | None = None, end: str | None = None, sample: bool = False) -> str:
    w = _window(start, end, sample)
    where = w + (" AND " if w else " WHERE ") + IS_API
    path = "regexp_replace(client_request_path, '[0-9a-f]{8}-[0-9a-f-]{27}|\\b\\d{3,}\\b|[0-9a-f]{24,}', '{id}')"
    path = f"regexp_replace({path}, '^/v2/domains/[^/]+', '/v2/domains/{{zone}}')"
    return f"""
SELECT
  cast(edge_response_status AS varchar) AS status,
  client_request_method || ' ' || substr({path}, 1, 70) AS endpoint,
  count(*) AS requests
FROM {table}
{where}
  AND edge_response_status IN (401, 429, 403, 404, 500, 502, 503)
GROUP BY 1, 2
ORDER BY requests DESC
LIMIT 20
""".strip()


def regions_sql(table: str, start: str | None = None, end: str | None = None, sample: bool = False) -> str:
    w = _window(start, end, sample)
    return f"""
SELECT 'country' AS dimension, upper(coalesce(client_country, '?')) AS name, count(*) AS requests
FROM {table}
{w}
GROUP BY 1, 2
ORDER BY requests DESC
LIMIT 12
""".strip()


def colo_latency_sql(table: str, start: str | None = None, end: str | None = None, sample: bool = False) -> str:
    w = _window(start, end, sample)
    where = w + (" AND " if w else " WHERE ") + f"{HOST} IN ('api.digitalocean.com', 'cloud.digitalocean.com')"
    return f"""
SELECT
  edge_colo_code AS colo,
  {HOST} AS host,
  count(*) AS requests,
  approx_quantile(edge_time_to_first_byte_ms, 0.5) AS p50_ttfb_ms,
  approx_quantile(edge_time_to_first_byte_ms, 0.95) AS p95_ttfb_ms
FROM {table}
{where}
  AND edge_colo_code IS NOT NULL
GROUP BY 1, 2
ORDER BY requests DESC
LIMIT 24
""".strip()


def otlp_sql(table: str, start: str | None = None, end: str | None = None, sample: bool = False) -> str:
    w = _window(start, end, sample)
    where = w + (" AND " if w else " WHERE ") + IS_OTLP
    return f"""
SELECT
  replace(replace({HOST}, 'otlp-', ''), '.digitalocean.com', '') AS region,
  count(*) AS requests,
  sum(CASE WHEN edge_response_status <> 200 THEN 1 ELSE 0 END) AS non_200,
  round(avg(edge_time_to_first_byte_ms), 1) AS avg_ttfb_ms,
  approx_quantile(edge_time_to_first_byte_ms, 0.95) AS p95_ttfb_ms
FROM {table}
{where}
GROUP BY 1
ORDER BY requests DESC
""".strip()


def mcp_funnel_sql(table: str, start: str | None = None, end: str | None = None, sample: bool = False) -> str:
    w = _window(start, end, sample)
    where = w + (" AND " if w else " WHERE ") + IS_MCP
    family = f"""
CASE
  WHEN {UA} ILIKE '%cursor%' THEN 'Cursor'
  WHEN {UA} ILIKE '%codex%' THEN 'codex-mcp-client'
  WHEN {UA} ILIKE '%Claude-User%' THEN 'Claude-User'
  WHEN {UA} ILIKE '%claude%' THEN 'claude-code'
  WHEN {UA} ILIKE '%opencode%' THEN 'opencode'
  WHEN {UA} ILIKE '%httpx%' THEN 'python-httpx'
  WHEN {UA} ILIKE 'Bun%' OR {UA} ILIKE '%bun/%' THEN 'Bun'
  WHEN {UA} ILIKE '%undici%' THEN 'undici'
  WHEN {UA} ILIKE 'node%' THEN 'node'
  ELSE 'other'
END
"""
    return f"""
SELECT
  {family} AS client,
  count(*) AS requests,
  approx_count_distinct(client_ip) AS distinct_ips,
  sum(CASE WHEN edge_response_status BETWEEN 200 AND 299 THEN 1 ELSE 0 END) AS ok,
  sum(CASE WHEN edge_response_status = 401 THEN 1 ELSE 0 END) AS challenge_401,
  sum(CASE WHEN edge_response_status = 404 THEN 1 ELSE 0 END) AS not_found
FROM {table}
{where}
GROUP BY 1
ORDER BY requests DESC
LIMIT 12
""".strip()


def page_cost_sql(table: str, start: str | None = None, end: str | None = None, sample: bool = False) -> str:
    w = _window(start, end, sample)
    where = (
        w
        + (" AND " if w else " WHERE ")
        + IS_WWW_DOCS
        + " AND client_request_method = 'GET'"
        + " AND (starts_with(coalesce(edge_response_content_type, ''), 'text/html') OR edge_response_content_type IS NULL)"
    )
    return f"""
WITH base AS (
  SELECT
    CASE
      WHEN ({CLIENT_CLASS}) = 'crawler' THEN 'crawler'
      WHEN ({CLIENT_CLASS}) = 'ai_client' THEN 'ai_client'
      WHEN ({CLIENT_CLASS}) = 'browser' THEN 'browser'
      ELSE 'other'
    END AS client_type,
    edge_response_bytes,
    origin_response_duration_ms,
    cache_cache_status
  FROM {table}
  {where}
)
SELECT
  client_type,
  count(*) AS views,
  round(avg(edge_response_bytes) / 1024.0, 1) AS kb_per_view,
  round(avg(origin_response_duration_ms), 0) AS origin_ms_per_view,
  round(100.0 * sum(CASE WHEN lower(coalesce(cache_cache_status, '')) IN ('bypass', 'miss', 'expired', 'updating') THEN 1 ELSE 0 END) / count(*), 1) AS cache_missish_pct
FROM base
GROUP BY 1
ORDER BY views DESC
""".strip()


def reliability_sql(table: str, start: str | None = None, end: str | None = None, sample: bool = False) -> str:
    w = _window(start, end, sample)
    # Only hosts that can produce interesting 5xx — avoids grouping every OTLP host.
    where = w + (" AND " if w else " WHERE ") + f"NOT ({IS_OTLP}) AND edge_response_status >= 500"
    return f"""
SELECT
  {HOST} AS host,
  count(*) AS s5xx,
  sum(CASE WHEN security_action IN ('block', 'challenge') THEN 1 ELSE 0 END) AS security_events
FROM {table}
{where}
GROUP BY 1
ORDER BY s5xx DESC
LIMIT 15
""".strip()
