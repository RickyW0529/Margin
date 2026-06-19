"""Centralized application settings for Margin.

MarginSettings consolidates environment-driven configuration for the API,
storage, LLM providers, observability, and deployment metadata. The module
exposes a cached ``get_settings()`` factory so that configuration is parsed
once per process.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import HttpUrl, PostgresDsn, SecretStr, field_validator
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
    monitoring_interval_seconds: int = 300

    # Audit
    audit_log_path: Path = Path.home() / ".margin" / "audit" / "provider_calls.jsonl"

    # Deployment
    environment: Literal["development", "test", "production"] = "development"
    service_name: str = "margin-api"
    service_version: str = "0.1.0"

    @field_validator(
        "llm_base_url",
        "embedding_base_url",
        "rerank_base_url",
        mode="before",
    )
    @classmethod
    def empty_optional_url_is_none(cls, value: object) -> object:
        """Allow Compose to pass empty optional URL variables.

        Docker Compose interpolates unset env vars as empty strings, but Pydantic
        would otherwise reject them for optional HttpUrl fields. Convert blanks
        to ``None`` so the field remains truly optional.
        """
        if isinstance(value, str) and not value.strip():
            return None
        return value


@lru_cache
def get_settings() -> MarginSettings:
    """Return cached settings instance.

    Caching avoids re-parsing environment variables on every call, which is
    important for dependency injection paths that may run frequently.
    """
    return MarginSettings()
