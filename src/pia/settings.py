"""Layered configuration.

Non-secret, environment-specific values come from configs/<env>.yaml.
Secrets come only from environment variables. An environment variable always
overrides the YAML value for the same setting.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


def config_dir() -> Path:
    return Path(os.getenv("PIA_CONFIG_DIR", ROOT / "configs"))


def _read_yaml(name: str) -> dict[str, Any]:
    path = config_dir() / f"{name}.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text()) or {}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PIA_", env_file=".env", extra="ignore")

    env: str = "dev"
    log_level: str = "INFO"
    database_url: str = "postgresql+psycopg://pia:pia@localhost:5432/pia"
    redis_url: str | None = None
    llm_provider: str = "fake"
    llm_model: str = "claude-sonnet-4-5"
    llm_timeout_s: float = 30.0
    llm_max_retries: int = 2
    review_token_budget: int = 200_000
    embedding_dim: int = 256
    cache_ttl_s: int = 300
    anthropic_api_key: str | None = None
    api_keys: str = ""
    cors_origins: list[str] = Field(default_factory=list)
    persistence: str = "memory"  # memory | postgres
    rate_limit_per_minute: int = 120
    sql_readonly_role: str | None = "pia_sql_readonly"
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: str | None = None
    oidc_teams_claim: str = "groups"


@lru_cache
def get_settings() -> Settings:
    env = os.getenv("PIA_ENV", "dev")
    merged = {**_read_yaml("base"), **_read_yaml(env)}
    overrides = {k: v for k, v in merged.items() if f"PIA_{k.upper()}" not in os.environ}
    return Settings(**overrides)
