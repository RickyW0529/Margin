"""Centralized application settings for Margin.

MarginSettings consolidates environment-driven configuration for the API,
storage, LLM providers, observability, and deployment metadata. The module
exposes a cached ``get_settings()`` factory so that configuration is parsed
once per process.
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, HttpUrl, PostgresDsn, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_DATABASE_URL = "postgresql+psycopg://margin:margin@localhost:5432/margin"
"""Default PostgreSQL URL used when no environment override is configured."""


class MarginSettings(BaseSettings):
    """Single source of truth for all Margin environment configuration.

    Attributes:
        database_url: SQLAlchemy connection URL for PostgreSQL.
        database_echo: Whether SQLAlchemy logs emitted SQL statements.
        database_pool_pre_ping: Whether to verify pool connections before checkout.
        llm_api_key: API key for the configured LLM provider.
        llm_base_url: Optional base URL for the LLM provider.
        llm_model: Model name used for LLM calls.
        embedding_base_url: Optional base URL for the embedding provider.
        embedding_api_key: Optional API key for the embedding provider.
        embedding_model: Model name used for embedding calls.
        embedding_dimension: Dimension of generated embedding vectors.
        rerank_base_url: Optional base URL for the rerank provider.
        rerank_api_key: Optional API key for the rerank provider.
        rerank_model: Model name used for reranking calls.
        websearch_api_key: Optional API key for web search integrations.
        log_level: Logging level name (e.g. "INFO").
        log_format: Output format for logs, either "json" or "console".
        metrics_enabled: Whether observability metrics are enabled.
        trace_id_header: HTTP header used to propagate trace identifiers.
        monitoring_interval_seconds: Interval between periodic monitoring runs.
        data_snapshot_root: Root directory for compressed provider payload snapshots.
        data_sync_on_startup: Whether startup should enqueue stale data sync work.
        data_freshness_timezone: Timezone used for data freshness calculations.
        data_smoke_symbols: Comma-separated A-share symbols used by smoke checks.
        tushare_token: Optional Tushare token used by real provider smoke.
        tushare_http_url: Optional Tushare-compatible API endpoint URL.
        audit_log_path: Filesystem path for the provider audit log.
        environment: Deployment environment name.
        service_name: Service identifier used in logs and metrics.
        service_version: Application version string.
    """

    model_config = SettingsConfigDict(
        env_prefix="MARGIN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: PostgresDsn = DEFAULT_DATABASE_URL
    database_echo: bool = False
    database_pool_pre_ping: bool = True

    # LLM
    llm_api_key: SecretStr | None = None
    llm_base_url: HttpUrl | None = None
    llm_model: str = "deepseek-v4-pro"

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

    # CORS / web frontend origin
    web_origin: str = "http://localhost:3000"

    # Local admin / encrypted provider secrets
    admin_api_token: SecretStr | None = None
    csrf_token: SecretStr | None = None
    secret_master_key: SecretStr | None = None
    secret_key_version: str = "local-v1"
    allow_local_provider_urls: bool = False
    resolve_provider_dns: bool = True

    # Data provider / warehouse sync
    tushare_token: SecretStr | None = None
    tushare_http_url: str | None = None
    data_snapshot_root: Path = Path(".margin") / "snapshots" / "data"
    data_sync_on_startup: bool = True
    data_freshness_timezone: str = "Asia/Shanghai"
    data_smoke_symbols: str = "000001.SZ"

    # Capacity / budget governance
    capacity_limit_version: str = "limits-v0.2.0"
    worker_max_concurrency: int = Field(default=4, gt=0)
    graph_max_concurrency: int = Field(default=2, gt=0)
    provider_default_rpm: int = Field(default=60, gt=0)
    provider_default_tpm: int = Field(default=200_000, gt=0)
    llm_daily_token_budget: int = Field(default=2_000_000, gt=0)
    llm_daily_cost_budget: Decimal = Field(default=Decimal("20.00"), gt=0)
    news_target_queue_high_water: int = Field(default=5_000, gt=0)
    embedding_batch_size: int = Field(default=64, gt=0)
    embedding_max_concurrency: int = Field(default=2, gt=0)
    database_pool_size: int = Field(default=10, gt=0)
    database_statement_timeout_ms: int = Field(default=30_000, gt=0)

    # Logging / Observability
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"
    metrics_enabled: bool = True
    trace_id_header: str = "x-margin-trace-id"
    monitoring_interval_seconds: int = 300

    # Audit
    audit_log_path: Path = Path(".margin") / "audit" / "provider_calls.jsonl"

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

        Args:
            value: Raw value supplied for an optional URL field.

        Returns:
            object: ``None`` when the value is an empty or whitespace-only string,
                otherwise the original value.
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
