"""Persistent APScheduler worker for automatic holdings monitoring."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler

from margin.core.logging_config import configure_logging
from margin.holdings_monitoring.repository import SQLAlchemyMonitoringRepository
from margin.holdings_monitoring.runner import (
    AKShareLatestPriceProvider,
    HoldingsMonitoringRunner,
    RepositoryNewsEventProvider,
)
from margin.holdings_monitoring.service import HoldingsMonitoringService
from margin.news.repository import NewsRepository
from margin.portfolio.repository import SQLAlchemyPortfolioRepository
from margin.portfolio.service import PortfolioService
from margin.settings import get_settings
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)
from margin.vector.embedding import EmbeddingProvider
from margin.vector.indexing_runner import DocumentIndexingRunner
from margin.vector.providers.openai_embedding import OpenAIEmbeddingProvider
from margin.vector.repository import VectorRepository

logger = logging.getLogger(__name__)


def build_scheduler(
    monitoring_job: Callable[[], None],
    *,
    interval_seconds: int,
    indexing_job: Callable[[], None] | None = None,
) -> BlockingScheduler:
    """Build the worker scheduler without starting it.

    Args:
        monitoring_job: Callable executed on each monitoring tick.
        interval_seconds: Seconds between successive job executions.
        indexing_job: Optional callable executed on each indexing tick.

    Returns:
        BlockingScheduler: Configured APScheduler instance with the requested jobs.
    """
    scheduler = BlockingScheduler(timezone="Asia/Shanghai")
    scheduler.add_job(
        monitoring_job,
        trigger="interval",
        seconds=interval_seconds,
        id="holdings-monitoring",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=max(30, interval_seconds),
        next_run_time=datetime.now(ZoneInfo("Asia/Shanghai")),
    )
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
    return scheduler


def build_monitoring_runner() -> HoldingsMonitoringRunner:
    """Build the production monitoring runner from centralized settings.

    Returns:
        HoldingsMonitoringRunner: Runner wired to database-backed portfolio and
            monitoring services, AKShare price data, and repository news events.
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
    portfolio_service = PortfolioService(
        repository=SQLAlchemyPortfolioRepository(session_factory)
    )
    monitoring_service = HoldingsMonitoringService(
        repository=SQLAlchemyMonitoringRepository(session_factory),
        portfolio_service=portfolio_service,
    )
    return HoldingsMonitoringRunner(
        portfolio_service=portfolio_service,
        monitoring_service=monitoring_service,
        price_provider=AKShareLatestPriceProvider(),
        news_provider=RepositoryNewsEventProvider(
            NewsRepository(session_factory)
        ),
    )


def build_document_indexing_runner() -> DocumentIndexingRunner:
    """Build the module 03 to module 04 persistent indexing worker.

    Returns:
        DocumentIndexingRunner: Runner wired to the news repository, vector store,
            and either an OpenAI embedding provider or a no-op fallback depending on
            configured credentials.
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
    if (
        settings.embedding_api_key is not None
        and settings.embedding_api_key.get_secret_value().strip()
        and settings.embedding_base_url is not None
    ):
        embedding_provider = OpenAIEmbeddingProvider(
            api_key=settings.embedding_api_key.get_secret_value(),
            base_url=str(settings.embedding_base_url),
            model=settings.embedding_model,
            dimension=settings.embedding_dimension,
        )
    else:
        embedding_provider = EmbeddingProvider(
            dim=settings.embedding_dimension,
        )
    return DocumentIndexingRunner(
        news_repository=NewsRepository(session_factory),
        vector_repository=VectorRepository(
            session_factory,
            dimension=settings.embedding_dimension,
        ),
        embedding_provider=embedding_provider,
    )


def main() -> None:
    """Start the persistent worker and run recurring monitoring sweeps."""
    settings = get_settings()
    configure_logging(
        log_level=settings.log_level,
        log_format=settings.log_format,
    )
    runner = build_monitoring_runner()
    indexing_runner = build_document_indexing_runner()

    def monitoring_job() -> None:
        try:
            snapshots = runner.run_once()
            logger.info(
                "holdings_monitoring_sweep_completed",
                extra={"snapshot_count": len(snapshots)},
            )
        except Exception:  # noqa: BLE001
            logger.exception("holdings_monitoring_sweep_failed")

    def indexing_job() -> None:
        try:
            indexed_count = indexing_runner.run_once()
            logger.info(
                "document_indexing_sweep_completed",
                extra={"indexed_count": indexed_count},
            )
        except Exception:  # noqa: BLE001
            logger.exception("document_indexing_sweep_failed")

    scheduler = build_scheduler(
        monitoring_job,
        interval_seconds=settings.monitoring_interval_seconds,
        indexing_job=indexing_job,
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
