from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Optional

from . import queries
from .ads import rows_as_dicts, run_sql
from .cache import cache
from .config import Settings

QueryFn = Callable[..., str]

_semaphores: dict[int, asyncio.Semaphore] = {}


def _query_sem(settings: Settings) -> asyncio.Semaphore:
    n = max(1, int(settings.ads_query_concurrency or 4))
    sem = _semaphores.get(n)
    if sem is None:
        sem = asyncio.Semaphore(n)
        _semaphores[n] = sem
    return sem


def _key(name: str, start: Optional[str], end: Optional[str], sample: bool) -> str:
    return f"{name}|{start or ''}|{end or ''}|sample={int(sample)}"


async def _cached_query(
    settings: Settings,
    name: str,
    sql: str,
    start: Optional[str],
    end: Optional[str],
    sample: bool,
    max_rows: int = 500,
) -> dict[str, Any]:
    ck = _key(name, start, end, sample)
    hit = cache.get(ck)
    if hit is not None:
        return {**hit, "cache": "hit"}

    async with _query_sem(settings):
        # Re-check after waiting — another coroutine may have filled the cache.
        hit = cache.get(ck)
        if hit is not None:
            return {**hit, "cache": "hit"}
        payload = await run_sql(settings, sql, max_rows=max_rows)

    result = {
        "name": name,
        "rows": rows_as_dicts(payload),
        "row_count": payload.get("rowCount"),
        "elapsed_ms": payload.get("elapsedMs"),
        "truncated": payload.get("truncated", False),
        "sample": sample,
        "cache": "miss",
    }
    cache.set(ck, result, settings.cache_ttl_seconds)
    return result


def _q(
    settings: Settings,
    name: str,
    sql_fn: QueryFn,
    start: Optional[str],
    end: Optional[str],
    sample: bool,
    max_rows: int = 500,
) -> Awaitable[dict[str, Any]]:
    sql = sql_fn(settings.ads_table, start, end, sample)
    return _cached_query(settings, name, sql, start, end, sample, max_rows=max_rows)


async def coverage(settings: Settings, start: Optional[str], end: Optional[str], sample: bool = True):
    return await _q(settings, "coverage", queries.coverage_sql, start, end, sample, max_rows=5)


async def overview(settings: Settings, start: Optional[str], end: Optional[str], sample: bool = True):
    return await _q(settings, "overview", queries.overview_sql, start, end, sample)


async def hourly(settings: Settings, start: Optional[str], end: Optional[str], sample: bool = True):
    return await _q(settings, "hourly", queries.hourly_mix_sql, start, end, sample, max_rows=48)


async def top_hosts(settings: Settings, start: Optional[str], end: Optional[str], sample: bool = True):
    return await _q(settings, "top_hosts", queries.top_hosts_sql, start, end, sample)


async def api_errors(settings: Settings, start: Optional[str], end: Optional[str], sample: bool = True):
    return await _q(settings, "api_errors", queries.api_errors_sql, start, end, sample)


async def regions(settings: Settings, start: Optional[str], end: Optional[str], sample: bool = True):
    return await _q(settings, "regions", queries.regions_sql, start, end, sample)


async def colo_latency(settings: Settings, start: Optional[str], end: Optional[str], sample: bool = True):
    return await _q(settings, "colo_latency", queries.colo_latency_sql, start, end, sample)


async def otlp(settings: Settings, start: Optional[str], end: Optional[str], sample: bool = True):
    return await _q(settings, "otlp", queries.otlp_sql, start, end, sample)


async def mcp(settings: Settings, start: Optional[str], end: Optional[str], sample: bool = True):
    return await _q(settings, "mcp", queries.mcp_funnel_sql, start, end, sample)


async def page_cost(settings: Settings, start: Optional[str], end: Optional[str], sample: bool = True):
    return await _q(settings, "page_cost", queries.page_cost_sql, start, end, sample)


async def reliability(settings: Settings, start: Optional[str], end: Optional[str], sample: bool = True):
    return await _q(settings, "reliability", queries.reliability_sql, start, end, sample)


SECTION_LOADERS = {
    "coverage": coverage,
    "overview": overview,
    "hourly": hourly,
    "top_hosts": top_hosts,
    "api_errors": api_errors,
    "regions": regions,
    "colo_latency": colo_latency,
    "otlp": otlp,
    "mcp": mcp,
    "page_cost": page_cost,
    "reliability": reliability,
}


async def bundle(
    settings: Settings,
    start: Optional[str],
    end: Optional[str],
    sample: bool = True,
) -> dict[str, Any]:
    """Run all MVP queries concurrently (wall time ≈ slowest query, not sum)."""
    names = list(SECTION_LOADERS)
    results = await asyncio.gather(
        *[SECTION_LOADERS[n](settings, start, end, sample) for n in names],
        return_exceptions=True,
    )
    sections: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for name, result in zip(names, results):
        if isinstance(result, Exception):
            errors[name] = str(result)
            sections[name] = {"name": name, "rows": [], "error": str(result), "cache": "error"}
        else:
            sections[name] = result
    return {
        "table": settings.ads_table,
        "window": {"start": start, "end": end},
        "sample": sample,
        "sections": sections,
        "errors": errors,
    }
