"""Persistence tests for the deterministic 20-year backfill control plane."""

from __future__ import annotations

from datetime import date

from margin.data.backfill.repository import SQLAlchemyBackfillRepository
from margin.data.backfill.service import BackfillApplicationService
from margin.platform_runtime.db_models import (
    BackfillCampaignRow,
    BackfillPartitionRow,
    BackfillQualityReportRow,
    IdempotencyKeyRow,
)
from margin.storage.base import Base
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)


def test_sqlalchemy_backfill_repository_persists_campaign_lifecycle(
    database_url: str,
) -> None:
    """Backfill lifecycle should survive process-local service reconstruction."""
    first_service = BackfillApplicationService(
        repository=_repository(database_url),
        today=date(2026, 7, 8),
    )

    created = first_service.create_campaign(
        campaign_name="persistent_full_market",
        providers=("tushare",),
        end_date=date(2006, 1, 31),
        idempotency_key="idem-backfill-persistent",
    )

    assert created.campaign.start_date == date(2006, 1, 1)
    assert created.partition_count > 0

    second_service = BackfillApplicationService(
        repository=_repository(database_url, reset=False),
        today=date(2026, 7, 8),
    )
    replayed = second_service.create_campaign(
        campaign_name="persistent_full_market",
        providers=("tushare",),
        end_date=date(2006, 1, 31),
        idempotency_key="idem-backfill-persistent",
    )

    assert replayed.campaign.campaign_id == created.campaign.campaign_id
    assert replayed.partition_count == created.partition_count

    run_summary = second_service.run_campaign(created.campaign.campaign_id)
    quality_report = second_service.verify_campaign(created.campaign.campaign_id)
    publish_result = second_service.publish_campaign(created.campaign.campaign_id)
    stored = second_service.get_campaign(created.campaign.campaign_id)

    assert run_summary.processed_partitions == created.partition_count
    assert quality_report.publish_allowed is True
    assert publish_result.status == "published"
    assert stored.campaign.status == "published"
    assert stored.quality_report_available is True


def _repository(
    database_url: str,
    *,
    reset: bool = True,
) -> SQLAlchemyBackfillRepository:
    """Create a SQLAlchemy backfill repository for integration tests."""
    engine = create_database_engine(DatabaseSettings(url=database_url))
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS platform")
        connection.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS ops")
    if reset:
        Base.metadata.drop_all(engine, tables=_backfill_tables(), checkfirst=True)
        Base.metadata.create_all(engine, tables=_backfill_tables())
    return SQLAlchemyBackfillRepository(create_session_factory(engine))


def _backfill_tables() -> list:
    """Return dependency-safe backfill platform tables."""
    return [
        BackfillQualityReportRow.__table__,
        BackfillPartitionRow.__table__,
        BackfillCampaignRow.__table__,
        IdempotencyKeyRow.__table__,
    ]
