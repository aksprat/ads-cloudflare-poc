"""ADS Query API client (POST /query with Bearer PAT)."""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from .config import Settings

log = logging.getLogger("dashboard.ads")

_client: Optional[httpx.AsyncClient] = None


class AdsQueryError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def rows_as_dicts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    cols = [c["name"] for c in payload.get("columns") or []]
    return [dict(zip(cols, row)) for row in payload.get("rows") or []]


async def get_client(settings: Settings) -> httpx.AsyncClient:
    global _client
    timeout = httpx.Timeout(settings.ads_timeout_seconds + 30.0, connect=30.0)
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=timeout)
    return _client


async def run_sql(settings: Settings, sql: str, max_rows: int = 500) -> dict[str, Any]:
    if not settings.digitalocean_token:
        raise AdsQueryError("DIGITALOCEAN_TOKEN is not set")

    url = f"https://{settings.ads_query_host}/query"
    body = {
        "sql": sql,
        "maxRows": max_rows,
        "timeoutSeconds": settings.ads_timeout_seconds,
    }
    headers = {
        "Authorization": f"Bearer {settings.digitalocean_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "cf-edge-dashboard/0.1",
    }
    client = await get_client(settings)
    resp = await client.post(url, headers=headers, json=body)

    if resp.status_code >= 400:
        raise AdsQueryError(
            f"ADS query failed with HTTP {resp.status_code}",
            status_code=resp.status_code,
            body=resp.text[:2000],
        )

    payload = resp.json()
    log.info(
        "query ok rows=%s truncated=%s elapsed_ms=%s",
        payload.get("rowCount"),
        payload.get("truncated"),
        payload.get("elapsedMs"),
    )
    return payload
