"""DB-backed data sync service tests."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete

from margin.data.db_models import (
    DataFreshnessStateRow,
    DataSyncRunRow,
    DataSyncWorkItemRow,
    ProviderEndpointRow,
)
from margin.data.endpoints import ProviderEndpoint
from margin.data.freshness import DataDomain, FreshnessCalculator, FreshnessStatus
from margin.data.sync_models import DataSyncRequest, DataSyncStatus
from margin.data.sync_service import (
    ProviderSyncError,
    SQLAlchemyDataSyncRepository,
    SyncService,
)
from margin.storage.base import Base
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)


@pytest.fixture
def sync_repository(database_url: str) -> SQLAlchemyDataSyncRepository:
    """sync repository."""
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    with session_factory.begin() as session:
        session.execute(delete(DataSyncWorkItemRow))
        session.execute(delete(DataSyncRunRow))
        session.execute(delete(ProviderEndpointRow))
    yield SQLAlchemyDataSyncRepository(session_factory)
    engine.dispose()


def test_claim_is_exclusive(sync_repository: SQLAlchemyDataSyncRepository) -> None:
    """claim is exclusive."""
    run = sync_repository.create_run(
        DataSyncRequest(provider="akshare", endpoint_codes=("daily_bar",)),
        endpoints=(ProviderEndpoint(provider="akshare", code="daily_bar", domain="market"),),
    )

    first = sync_repository.claim_next_endpoint(run.run_id, worker_id="worker-1")
    second = sync_repository.claim_next_endpoint(run.run_id, worker_id="worker-2")

    assert first is not None
    assert second is None
    assert first.status == DataSyncStatus.RUNNING


def test_failed_endpoint_does_not_advance_cursor(
    sync_repository: SQLAlchemyDataSyncRepository,
) -> None:
    """failed endpoint does not advance cursor."""
    run = sync_repository.create_run(
        DataSyncRequest(provider="akshare", endpoint_codes=("daily_bar",)),
        endpoints=(ProviderEndpoint(provider="akshare", code="daily_bar", domain="market"),),
    )
    item = sync_repository.claim_next_endpoint(run.run_id, worker_id="worker-1")
    assert item is not None

    def failing_handler(_item):
        """failing handler."""
        raise ProviderSyncError("provider_500", "upstream failed")

    service = SyncService(
        sync_repository,
        handlers={("akshare", "daily_bar"): failing_handler},
    )
    result = service.execute_endpoint(item, now=datetime(2026, 6, 22, tzinfo=UTC))

    assert result.status == DataSyncStatus.FAILED_RETRYABLE
    assert result.cursor_after is None
    stored = sync_repository.get_work_item(item.work_item_id)
    assert stored is not None
    assert stored.cursor_after is None


def test_worker_claims_global_work_in_endpoint_sequence(
    sync_repository: SQLAlchemyDataSyncRepository,
) -> None:
    """Global workers process prerequisites before dependent endpoints."""
    run = sync_repository.create_run(
        DataSyncRequest(provider="tushare"),
        endpoints=(
            ProviderEndpoint(
                provider="tushare",
                code="security_master",
                domain="security",
            ),
            ProviderEndpoint(
                provider="tushare",
                code="daily_bar",
                domain="market",
            ),
        ),
    )

    first = sync_repository.claim_next(worker_id="worker-1")
    assert first is not None
    assert first.run_id == run.run_id
    assert first.endpoint_code == "security_master"

    sync_repository.mark_succeeded(
        first.work_item_id,
        cursor_after="security-cursor",
        finished_at=datetime(2026, 6, 22, tzinfo=UTC),
    )
    second = sync_repository.claim_next(worker_id="worker-1")

    assert second is not None
    assert second.endpoint_code == "daily_bar"


def test_expired_running_work_is_reclaimed(
    sync_repository: SQLAlchemyDataSyncRepository,
) -> None:
    """A crashed worker cannot leave a sync item permanently running."""
    run = sync_repository.create_run(
        DataSyncRequest(provider="tushare", endpoint_codes=("daily_bar",)),
        endpoints=(
            ProviderEndpoint(
                provider="tushare",
                code="daily_bar",
                domain="market",
            ),
        ),
    )
    claimed_at = datetime(2026, 6, 22, tzinfo=UTC)
    first = sync_repository.claim_next_endpoint(
        run.run_id,
        worker_id="worker-1",
        now=claimed_at,
        lease_seconds=30,
    )

    assert first is not None
    assert (
        sync_repository.claim_next(
            worker_id="worker-2",
            now=claimed_at + timedelta(seconds=20),
        )
        is None
    )

    reclaimed = sync_repository.claim_next(
        worker_id="worker-2",
        now=claimed_at + timedelta(seconds=31),
        lease_seconds=30,
    )

    assert reclaimed is not None
    assert reclaimed.work_item_id == first.work_item_id
    assert reclaimed.claimed_by == "worker-2"


def test_run_is_reconciled_after_each_terminal_item(
    sync_repository: SQLAlchemyDataSyncRepository,
) -> None:
    """Run counters and terminal status reflect persisted work-item outcomes."""
    run = sync_repository.create_run(
        DataSyncRequest(provider="tushare"),
        endpoints=(
            ProviderEndpoint(provider="tushare", code="security_master", domain="security"),
            ProviderEndpoint(provider="tushare", code="daily_bar", domain="market"),
        ),
    )
    first = sync_repository.claim_next(worker_id="worker-1")
    assert first is not None
    sync_repository.mark_succeeded(
        first.work_item_id,
        cursor_after="one",
        finished_at=datetime(2026, 6, 22, tzinfo=UTC),
    )

    running = sync_repository.get_run(run.run_id)
    assert running is not None
    assert running.status == DataSyncStatus.RUNNING
    assert running.completed_count == 1

    second = sync_repository.claim_next(worker_id="worker-1")
    assert second is not None
    sync_repository.mark_succeeded(
        second.work_item_id,
        cursor_after="two",
        finished_at=datetime(2026, 6, 22, tzinfo=UTC),
    )

    completed = sync_repository.get_run(run.run_id)
    assert completed is not None
    assert completed.status == DataSyncStatus.SUCCEEDED
    assert completed.completed_count == 2
    assert completed.finished_at is not None


def test_latest_run_can_be_recovered_by_orchestration_requester(
    sync_repository: SQLAlchemyDataSyncRepository,
) -> None:
    """Pipeline retries can recover their durable data-sync run after restart."""
    first = sync_repository.create_run(
        DataSyncRequest(
            provider="tushare",
            requested_by="valuation:vdr-1",
        ),
        endpoints=(
            ProviderEndpoint(
                provider="tushare",
                code="security_master",
                domain="security",
            ),
        ),
    )
    second = sync_repository.create_run(
        DataSyncRequest(
            provider="tushare",
            requested_by="valuation:vdr-1",
        ),
        endpoints=(
            ProviderEndpoint(
                provider="tushare",
                code="security_master",
                domain="security",
            ),
        ),
    )

    recovered = sync_repository.find_latest_run(
        requested_by="valuation:vdr-1"
    )

    assert recovered is not None
    assert recovered.run_id == second.run_id
    assert recovered.run_id != first.run_id


def test_successful_endpoint_records_queryable_freshness(
    sync_repository: SQLAlchemyDataSyncRepository,
) -> None:
    """A successful endpoint updates freshness used by valuation orchestration."""
    sync_repository.create_run(
        DataSyncRequest(provider="tushare"),
        endpoints=(
            ProviderEndpoint(
                provider="tushare",
                code="daily_bar",
                domain="market",
            ),
        ),
    )
    item = sync_repository.claim_next(worker_id="worker-1")
    assert item is not None
    finished_at = datetime(2026, 6, 22, 18, 30, tzinfo=UTC)

    sync_repository.mark_succeeded(
        item.work_item_id,
        cursor_after="2026-06-22",
        finished_at=finished_at,
    )

    with sync_repository._session_factory() as session:
        row = session.query(DataFreshnessStateRow).filter_by(
            provider="tushare",
            endpoint_code="daily_bar",
            as_of_date=finished_at.date(),
        ).one()
    assert row.status == FreshnessStatus.FRESH.value
    assert row.observed_at == finished_at


def test_market_expected_as_of_waits_for_provider_availability_time() -> None:
    """market expected as of waits for provider availability time."""
    calculator = FreshnessCalculator(
        trading_days={date(2026, 6, 19), date(2026, 6, 22)},
        timezone="Asia/Shanghai",
        market_available_time=time(18, 0),
    )

    expectation = calculator.expected_as_of(
        DataDomain.MARKET,
        now=datetime(2026, 6, 22, 17, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert expectation.as_of_date == date(2026, 6, 19)
    assert expectation.expected_at == datetime(2026, 6, 19, 18, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def test_freshness_state_is_stale_when_latest_observation_lags_expected() -> None:
    """freshness state is stale when laobservation lags expected."""
    calculator = FreshnessCalculator(
        trading_days={date(2026, 6, 19), date(2026, 6, 22)},
        timezone="Asia/Shanghai",
        market_available_time=time(18, 0),
    )

    state = calculator.evaluate(
        DataDomain.MARKET,
        now=datetime(2026, 6, 22, 19, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        latest_observed_at=datetime(2026, 6, 19, 18, 5, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert state.status == FreshnessStatus.STALE
    assert state.as_of_date == date(2026, 6, 22)
    assert state.lag_seconds == 258_900
