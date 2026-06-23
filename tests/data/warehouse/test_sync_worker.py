"""End-to-end worker execution for durable data-sync runs."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, select

from margin.data.db_models import (
    CanonicalIndicatorValueRow,
    DataSyncRunRow,
    DataSyncWorkItemRow,
    ProviderEndpointRow,
    RawDataSnapshotRow,
    SecurityIndustryMembershipRow,
    SecurityMasterRow,
    SecurityProviderIdentifierRow,
    SourceSchemaFieldRow,
    StandardizedIndicatorFactRow,
)
from margin.data.endpoints import ProviderEndpoint, ProviderEndpointRegistry
from margin.data.ingestion import DataWarehouseIngestionStack
from margin.data.sync_models import DataSyncRequest, DataSyncStatus
from margin.data.sync_worker import DataSyncWorker
from margin.data.warehouse_repository import CanonicalQuery
from margin.storage.base import Base
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)

DECISION_AT = datetime(2026, 6, 22, tzinfo=UTC)


class FakeProvider:
    """Provider double covering security master and daily bars."""

    name = "fake"

    def get_securities(self, as_of: datetime) -> list[dict]:
        """Return one listed A-share security."""
        assert as_of == DECISION_AT
        return [
            {
                "symbol": "000001.SZ",
                "name": "平安银行",
                "industry": "银行",
                "list_date": "19910403",
                "fetched_at": DECISION_AT,
                "available_at": DECISION_AT,
                "source": self.name,
            }
        ]

    def get_bars(
        self,
        symbols: list[str],
        start: datetime,
        end: datetime,
        frequency: str = "1d",
    ) -> list[dict]:
        """Return one daily bar for the synchronized security master."""
        assert symbols == ["000001.SZ"]
        assert start == DECISION_AT
        assert end == DECISION_AT
        return [
            {
                "symbol": "000001.SZ",
                "date": DECISION_AT,
                "open": 9.5,
                "high": 10.5,
                "low": 9.0,
                "close": 10.0,
                "volume": 1000,
                "amount": 10000,
                "frequency": frequency,
                "fetched_at": DECISION_AT,
                "available_at": DECISION_AT,
                "source": self.name,
            }
        ]


def test_worker_executes_security_then_market_data(
    database_url: str,
    tmp_path,
) -> None:
    """A pending run reaches succeeded with real persisted warehouse outputs."""
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    with session_factory.begin() as session:
        for model in (
            CanonicalIndicatorValueRow,
            StandardizedIndicatorFactRow,
            SecurityIndustryMembershipRow,
            SecurityProviderIdentifierRow,
            SecurityMasterRow,
            SourceSchemaFieldRow,
            RawDataSnapshotRow,
            DataSyncWorkItemRow,
            DataSyncRunRow,
            ProviderEndpointRow,
        ):
            session.execute(delete(model))
    registry = ProviderEndpointRegistry(
        (
            ProviderEndpoint(provider="fake", code="security_master", domain="security"),
            ProviderEndpoint(provider="fake", code="daily_bar", domain="market"),
        )
    )
    stack = DataWarehouseIngestionStack(
        session_factory=session_factory,
        snapshot_root=tmp_path,
        endpoint_registry=registry,
        default_provider="fake",
    )
    run = stack.create_sync_run(
        DataSyncRequest(
            provider="fake",
            endpoint_codes=("security_master", "daily_bar"),
            backfill_start=DECISION_AT,
            backfill_end=DECISION_AT,
        )
    )
    worker = DataSyncWorker(
        stack=stack,
        providers={"fake": FakeProvider()},
        worker_id="test-worker",
    )

    processed = worker.run_once(
        max_items=10,
        now=DECISION_AT,
        run_id=run.run_id,
    )

    assert processed == 2
    stored_run = stack.sync_repository.get_run(run.run_id)
    assert stored_run is not None
    assert stored_run.status == DataSyncStatus.SUCCEEDED
    with session_factory() as session:
        security = session.scalar(
            select(SecurityMasterRow).where(
                SecurityMasterRow.security_id == "000001.SZ"
            )
        )
    assert security is not None
    values = stack.warehouse.canonical_values(
        CanonicalQuery(
            security_ids=("000001.SZ",),
            indicator_ids=("close",),
            decision_at=DECISION_AT,
        )
    )
    assert len(values) == 1
    engine.dispose()
