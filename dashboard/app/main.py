from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .ads import AdsQueryError
from .cache import cache
from .config import get_settings
from . import service

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("dashboard")

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"

app = FastAPI(title="CF Edge Log Dashboard", version="0.2.0")
app.mount("/assets", StaticFiles(directory=STATIC), name="assets")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
async def health() -> dict:
    s = get_settings()
    return {
        "ok": True,
        "connector": "adbc_quack",
        "query_host": s.ads_query_host,
        "table": s.ads_table,
        "token_configured": bool(s.ads_quack_token),
        "concurrency": s.ads_query_concurrency,
        "hint": "Queries go through ADBC Quack. Iceberg holds raw rows; use sample=true (1 minute/hour) for faster first loads.",
    }


@app.post("/api/cache/clear")
async def clear_cache() -> dict:
    cache.clear()
    return {"cleared": True}


def _params(
    start: Optional[str] = None,
    end: Optional[str] = None,
    sample: bool = Query(True, description="If true, keep only minute==30 (≈1/60 of rows)"),
):
    return start, end, sample


@app.get("/api/coverage")
async def api_coverage(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    sample: bool = Query(True),
):
    return await _wrap(service.coverage, start, end, sample)


@app.get("/api/overview")
async def api_overview(
    start: Optional[str] = None, end: Optional[str] = None, sample: bool = Query(True)
):
    return await _wrap(service.overview, start, end, sample)


@app.get("/api/hourly")
async def api_hourly(
    start: Optional[str] = None, end: Optional[str] = None, sample: bool = Query(True)
):
    return await _wrap(service.hourly, start, end, sample)


@app.get("/api/top-hosts")
async def api_top_hosts(
    start: Optional[str] = None, end: Optional[str] = None, sample: bool = Query(True)
):
    return await _wrap(service.top_hosts, start, end, sample)


@app.get("/api/api-errors")
async def api_api_errors(
    start: Optional[str] = None, end: Optional[str] = None, sample: bool = Query(True)
):
    return await _wrap(service.api_errors, start, end, sample)


@app.get("/api/regions")
async def api_regions(
    start: Optional[str] = None, end: Optional[str] = None, sample: bool = Query(True)
):
    return await _wrap(service.regions, start, end, sample)


@app.get("/api/colo-latency")
async def api_colo_latency(
    start: Optional[str] = None, end: Optional[str] = None, sample: bool = Query(True)
):
    return await _wrap(service.colo_latency, start, end, sample)


@app.get("/api/otlp")
async def api_otlp(
    start: Optional[str] = None, end: Optional[str] = None, sample: bool = Query(True)
):
    return await _wrap(service.otlp, start, end, sample)


@app.get("/api/mcp")
async def api_mcp(
    start: Optional[str] = None, end: Optional[str] = None, sample: bool = Query(True)
):
    return await _wrap(service.mcp, start, end, sample)


@app.get("/api/page-cost")
async def api_page_cost(
    start: Optional[str] = None, end: Optional[str] = None, sample: bool = Query(True)
):
    return await _wrap(service.page_cost, start, end, sample)


@app.get("/api/reliability")
async def api_reliability(
    start: Optional[str] = None, end: Optional[str] = None, sample: bool = Query(True)
):
    return await _wrap(service.reliability, start, end, sample)


@app.get("/api/bundle")
async def api_bundle(
    start: Optional[str] = Query("2026-11-10 14:00:00 UTC"),
    end: Optional[str] = Query("2026-11-10 15:00:00 UTC"),
    sample: bool = Query(True, description="Default true: minute==30 sample for fast dashboards"),
):
    return await _wrap(service.bundle, start, end, sample)


async def _wrap(fn, start: Optional[str], end: Optional[str], sample: bool = True):
    settings = get_settings()
    try:
        return await fn(settings, start, end, sample)
    except AdsQueryError as e:
        log.exception("ADS query error")
        raise HTTPException(status_code=502, detail={"message": str(e), "body": e.body}) from e
    except Exception as e:
        log.exception("unexpected error")
        raise HTTPException(status_code=500, detail=str(e)) from e
