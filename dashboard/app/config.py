from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    ads_query_host: str = "ads-cloudflare-poc-k9pb59-tor1.aidp-preview.ondigitalocean.com"
    digitalocean_token: str = ""
    ads_table: str = "tabular.ads_cloudflare_poc.cf_request_log"
    cache_ttl_seconds: int = 1800  # 30 min — aggregates are expensive; reuse aggressively
    ads_timeout_seconds: int = 180
    ads_query_concurrency: int = 2


@lru_cache
def get_settings() -> Settings:
    return Settings()
