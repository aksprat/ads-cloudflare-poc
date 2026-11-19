"""Normalize ADS Quack credentials from Overview Connection Details."""

from __future__ import annotations

import os


def normalize_host(host: str) -> str:
    host = (host or "").strip()
    if "://" in host:
        host = host.split("://", 1)[1]
    host = host.rstrip("/")
    # Overview uses host:443
    if ":" not in host.split("]")[-1]:
        host = f"{host}:443"
    return host


def quack_token(
    token: str | None = None,
    user: str | None = None,
    password: str | None = None,
) -> str:
    """Overview DuckDB snippet uses TOKEN 'reader:<password>'.

    Accepts either the full ``reader:…`` string or separate user/password.
    """
    token = (token or os.getenv("ADS_QUACK_TOKEN") or "").strip()
    user = (user or os.getenv("ADS_QUACK_USER") or os.getenv("ADS_READER_USER") or "reader").strip()
    password = (
        password
        or os.getenv("ADS_QUACK_PASSWORD")
        or os.getenv("ADS_READER_PASSWORD")
        or ""
    ).strip()

    if token:
        # Already user:password (Overview Show token / copied ATTACH snippet)
        if ":" in token and not token.startswith("doo_"):
            return token
        # Bare password pasted by mistake
        return f"{user}:{token}"

    if password:
        return f"{user}:{password}"

    return ""


def table_fqn(table: str | None = None, *, for_attach_alias: str | None = "srv") -> str:
    """HTTP API uses tabular.<schema>.<table>; after ATTACH prefix with srv."""
    table = (table or os.getenv("ADS_TABLE") or "tabular.ads_cloudflare_poc.cf_request_log").strip()
    if for_attach_alias and not table.startswith(f"{for_attach_alias}."):
        return f"{for_attach_alias}.{table}"
    return table
