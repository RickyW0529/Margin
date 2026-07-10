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

from pydantic import Field, PostgresDsn, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

DEFAULT_DATABASE_URL = "postgresql+psycopg://margin:margin@localhost:5432/margin"
"""Default PostgreSQL URL used when no environment override is configured."""

DEFAULT_SECRET_MASTER_KEY = "dev-only-change-me-32-byte-key!!"
"""Stable local default key for encrypted provider secrets in personal mode."""


class MarginSettings(BaseSettings):
    """Single source of truth for all Margin environment configuration.."""

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
    admin_api_token: SecretStr | None = None
    allow_local_provider_urls: bool = False
    resolve_provider_dns: bool = True

    # Data provider / warehouse sync
    data_snapshot_root: Path = Path(".margin") / "snapshots" / "data"
    data_sync_on_startup: bool = True
    data_freshness_timezone: str = "Asia/Shanghai"
    data_smoke_symbols: str = "000001.SZ"

    # Agent workspace
    agent_workspace_root: Path = Path(".")
    agent_code_tools_enabled: bool = False

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

    @model_validator(mode="after")
    def validate_production_secrets(self) -> MarginSettings:
        """Reject local development credentials in production mode.

        Returns:
            MarginSettings: .
        """
        if self.environment != "production":
            return self
        if self.secret_master_key.get_secret_value() == DEFAULT_SECRET_MASTER_KEY:
            raise ValueError(
                "MARGIN_SECRET_MASTER_KEY must be set to a non-default value in production"
            )
        if self.admin_api_token is None or not self.admin_api_token.get_secret_value():
            raise ValueError("MARGIN_ADMIN_API_TOKEN is required in production")
        database_url = make_url(str(self.database_url))
        if database_url.username == "margin" and database_url.password == "margin":
            raise ValueError(
                "MARGIN_DATABASE_URL must not use default margin:margin credentials in production"
            )
        return self


@lru_cache
def get_settings() -> MarginSettings:
    """Return cached settings instance.

    Returns:
        MarginSettings: .
    """
    return MarginSettings()
