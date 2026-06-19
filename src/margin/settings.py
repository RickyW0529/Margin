"""Centralized application settings for Margin."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, HttpUrl, PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class MarginSettings(BaseSettings):
    """Single source of truth for all Margin environment configuration."""

    model_config = SettingsConfigDict(
        env_prefix="MARGIN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: PostgresDsn = "postgresql+psycopg://margin:margin@localhost:5432/margin"
    database_echo: bool = False
    database_pool_pre_ping: bool = True

    # LLM
    llm_api_key: SecretStr | None = None
    llm_base_url: HttpUrl | None = None
    llm_model: str = "gpt-4o-mini"

    # Embedding
    embedding_base_url: HttpUrl | None = None
    embedding_api_key: SecretStr | None = None
    embedding_model: str = "text-embedding-3-small"
    embedding_dimension: int = 1536

    # Rerank
    rerank_base_url: HttpUrl | None = None
    rerank_api_key: SecretStr | None = None
    rerank_model: str = ""

    # WebSearch
    websearch_api_key: SecretStr | None = None

    # Logging / Observability
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"
    metrics_enabled: bool = True
    trace_id_header: str = "x-margin-trace-id"

    # Audit
    audit_log_path: Path = Path.home() / ".margin" / "audit" / "provider_calls.jsonl"

    # Deployment
    environment: Literal["development", "test", "production"] = "development"
    service_name: str = "margin-api"
    service_version: str = "0.1.0"


@lru_cache
def get_settings() -> MarginSettings:
    """Return cached settings instance."""
    return MarginSettings()
