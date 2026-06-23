"""Persistent APScheduler worker for the v0.2 research pipeline."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler

from margin.core.logging_config import configure_logging
from margin.core.secret_store import SecretStore, SQLAlchemySecretRepository
from margin.data.ingestion import DataWarehouseIngestionStack
from margin.data.sync_worker import DataSyncWorker
from margin.news.repository import NewsRepository
from margin.settings import MarginSettings, get_settings
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)
from margin.strategy.provider_runtime import (
    ProviderRuntimeFactory,
    ProviderRuntimeResolver,
)
from margin.strategy.repository import SQLAlchemyStrategyRepository
from margin.vector.indexing_runner import DocumentIndexingRunner
from margin.vector.repository import VectorRepository

logger = logging.getLogger(__name__)


def build_scheduler(
    *,
    interval_seconds: int,
    indexing_job: Callable[[], None] | None = None,
    data_sync_job: Callable[[], None] | None = None,
    orchestration_job: Callable[[], None] | None = None,
) -> BlockingScheduler:
    """Build the worker scheduler without starting it.

    Args:
        interval_seconds: Seconds between successive job executions.
        indexing_job: Optional callable executed on each indexing tick.
        data_sync_job: Optional callable executed on each data-sync tick.
        orchestration_job: Optional callable that wakes durable orchestration steps.

    Returns:
        BlockingScheduler: Configured APScheduler instance with the requested jobs.
    """
    scheduler = BlockingScheduler(timezone="Asia/Shanghai")
    if indexing_job is not None:
        scheduler.add_job(
            indexing_job,
            trigger="interval",
            seconds=interval_seconds,
            id="document-indexing",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=max(30, interval_seconds),
            next_run_time=datetime.now(ZoneInfo("Asia/Shanghai")),
        )
    if data_sync_job is not None:
        scheduler.add_job(
            data_sync_job,
            trigger="interval",
            seconds=interval_seconds,
            id="data-provider-sync",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=max(30, interval_seconds),
            next_run_time=datetime.now(ZoneInfo("Asia/Shanghai")),
        )
    if orchestration_job is not None:
        scheduler.add_job(
            orchestration_job,
            trigger="interval",
            seconds=interval_seconds,
            id="orchestration-steps",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=max(30, interval_seconds),
            next_run_time=datetime.now(ZoneInfo("Asia/Shanghai")),
        )
    return scheduler


def build_document_indexing_runner() -> DocumentIndexingRunner:
    """Build the module 03 to module 04 persistent indexing worker.

    Returns:
        DocumentIndexingRunner: Runner wired to the active versioned embedding
            Provider and persistent vector repository.
    """
    settings = get_settings()
    engine = create_database_engine(
        DatabaseSettings(
            url=str(settings.database_url),
            echo=settings.database_echo,
            pool_pre_ping=settings.database_pool_pre_ping,
        )
    )
    session_factory = create_session_factory(engine)
    embedding_provider = build_worker_provider_runtime_factory(
        settings
    ).build_embedding().adapter
    return DocumentIndexingRunner(
        news_repository=NewsRepository(session_factory),
        vector_repository=VectorRepository(
            session_factory,
            dimension=embedding_provider.dim,
        ),
        embedding_provider=embedding_provider,
    )


def build_data_ingestion_stack(
    settings: MarginSettings | None = None,
    *,
    default_provider: str = "tushare",
) -> DataWarehouseIngestionStack:
    """Build the production data warehouse ingestion stack."""
    resolved = settings or get_settings()
    engine = create_database_engine(
        DatabaseSettings(
            url=str(resolved.database_url),
            echo=resolved.database_echo,
            pool_pre_ping=resolved.database_pool_pre_ping,
        )
    )
    return DataWarehouseIngestionStack(
        session_factory=create_session_factory(engine),
        snapshot_root=resolved.data_snapshot_root,
        default_provider=default_provider,
    )


def build_worker_provider_runtime_factory(
    settings: MarginSettings,
) -> ProviderRuntimeFactory:
    """Build the worker's strict active-config Provider factory."""
    if settings.secret_master_key is None:
        raise RuntimeError("MARGIN_SECRET_MASTER_KEY is not configured")
    engine = create_database_engine(
        DatabaseSettings(
            url=str(settings.database_url),
            echo=settings.database_echo,
            pool_pre_ping=settings.database_pool_pre_ping,
        )
    )
    session_factory = create_session_factory(engine)
    return ProviderRuntimeFactory(
        ProviderRuntimeResolver(
            SQLAlchemyStrategyRepository(session_factory),
            SecretStore(
                SQLAlchemySecretRepository(session_factory),
                master_key=settings.secret_master_key.get_secret_value(),
                key_version=settings.secret_key_version,
            ),
        )
    )


def build_data_sync_worker(
    settings: MarginSettings | None = None,
) -> DataSyncWorker:
    """Build the production durable data-sync worker and configured providers."""
    resolved = settings or get_settings()
    factory = build_worker_provider_runtime_factory(resolved)
    providers: dict[str, object] = {}
    version_ids: dict[str, str] = {}
    for provider_name, builder in (
        ("tushare", factory.build_tushare),
        ("akshare", factory.build_akshare),
    ):
        try:
            runtime = builder()
        except (LookupError, RuntimeError, ValueError):
            continue
        providers[provider_name] = runtime.adapter
        version_ids[provider_name] = runtime.config_version_id
    if not providers:
        raise RuntimeError("no active market-data Provider is configured")
    default_provider = "tushare" if "tushare" in providers else "akshare"
    return DataSyncWorker(
        stack=build_data_ingestion_stack(
            resolved,
            default_provider=default_provider,
        ),
        providers=providers,
        provider_config_version_ids=version_ids,
        worker_id=f"{resolved.service_name}-data-sync",
    )


def main() -> None:
    """Start the persistent worker and run recurring pipeline sweeps."""
    settings = get_settings()
    configure_logging(
        log_level=settings.log_level,
        log_format=settings.log_format,
    )
    indexing_runner = build_document_indexing_runner()
    data_sync_worker = build_data_sync_worker(settings)

    def indexing_job() -> None:
        """indexing job."""
        try:
            indexed_count = indexing_runner.run_once()
            logger.info(
                "document_indexing_sweep_completed",
                extra={"indexed_count": indexed_count},
            )
        except Exception:  # noqa: BLE001
            logger.exception("document_indexing_sweep_failed")

    def data_sync_job() -> None:
        """data sync job."""
        try:
            processed_count = data_sync_worker.run_once(
                max_items=settings.worker_max_concurrency,
            )
            logger.info(
                "data_provider_sync_sweep_completed",
                extra={"processed_count": processed_count},
            )
        except Exception:  # noqa: BLE001
            logger.exception("data_provider_sync_failed")

    def orchestration_job() -> None:
        """Claim and execute durable valuation-discovery steps."""
        try:
            from margin.api.dependencies import (
                get_valuation_discovery_step_worker,
            )

            step_worker = get_valuation_discovery_step_worker()
            processed_count = 0
            for _ in range(settings.worker_max_concurrency):
                if not step_worker.run_once(now=datetime.now(UTC)):
                    break
                processed_count += 1
            logger.info(
                "valuation_discovery_sweep_completed",
                extra={"processed_count": processed_count},
            )
        except Exception:  # noqa: BLE001
            logger.exception("valuation_discovery_sweep_failed")

    scheduler = build_scheduler(
        interval_seconds=settings.monitoring_interval_seconds,
        indexing_job=indexing_job,
        data_sync_job=data_sync_job,
        orchestration_job=orchestration_job,
    )
    logger.info(
        "margin_worker_started",
        extra={
            "monitoring_interval_seconds": settings.monitoring_interval_seconds,
        },
    )
    scheduler.start()


if __name__ == "__main__":
    main()
