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
    """Overview DuckDB/ADBC snippet uses TOKEN 'reader:<password>'."""
    token = (token or os.getenv("ADS_QUACK_TOKEN") or "").strip()
    user = (user or os.getenv("ADS_QUACK_USER") or os.getenv("ADS_READER_USER") or "reader").strip()
    password = (
        password
        or os.getenv("ADS_QUACK_PASSWORD")
        or os.getenv("ADS_READER_PASSWORD")
        or ""
    ).strip()

    if token:
        if ":" in token and not token.startswith("doo_"):
            return token
        return f"{user}:{token}"

    if password:
        return f"{user}:{password}"

    return ""
