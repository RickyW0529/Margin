"""Centralized application settings for Margin.

MarginSettings consolidates environment-driven configuration for the API,
storage, observability, and deployment metadata. Provider credentials are stored
in encrypted provider database tables instead of environment variables. The module
exposes a cached ``get_settings()`` factory so that configuration is parsed
once per process.
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_DATABASE_URL = "postgresql+psycopg://margin:margin@localhost:5432/margin"
"""Default PostgreSQL URL used when no environment override is configured."""

DEFAULT_SECRET_MASTER_KEY = "dev-only-change-me-32-byte-key!!"
"""Stable local default key for encrypted provider secrets in personal mode."""


class MarginSettings(BaseSettings):
    """Single source of truth for all Margin environment configuration.

    Attributes:
        database_url: SQLAlchemy connection URL for PostgreSQL.
        database_echo: Whether SQLAlchemy logs emitted SQL statements.
        database_pool_pre_ping: Whether to verify pool connections before checkout.
        log_level: Logging level name (e.g. "INFO").
        log_format: Output format for logs, either "json" or "console".
        metrics_enabled: Whether observability metrics are enabled.
        trace_id_header: HTTP header used to propagate trace identifiers.
        monitoring_interval_seconds: Interval between periodic monitoring runs.
        data_snapshot_root: Root directory for compressed provider payload snapshots.
        data_sync_on_startup: Whether startup should enqueue stale data sync work.
        data_freshness_timezone: Timezone used for data freshness calculations.
        data_smoke_symbols: Comma-separated A-share symbols used by smoke checks.
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

    # CORS / web frontend origin
    web_origin: str = "http://localhost:3000"

    # Encrypted provider secrets / SSRF controls
    secret_master_key: SecretStr = SecretStr(DEFAULT_SECRET_MASTER_KEY)
    secret_key_version: str = "local-v1"
    allow_local_provider_urls: bool = False
    resolve_provider_dns: bool = True

    # Data provider / warehouse sync
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


@lru_cache
def get_settings() -> MarginSettings:
    """Return cached settings instance.

    Caching avoids re-parsing environment variables on every call, which is
    important for dependency injection paths that may run frequently.
    """
    return MarginSettings()
