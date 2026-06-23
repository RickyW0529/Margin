"""End-to-end data provider warehouse ingestion test."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from margin.data.db_models import (
    CanonicalIndicatorValueRow,
    DataSyncRunRow,
    DataSyncWorkItemRow,
    ProviderEndpointRow,
    RawDataSnapshotRow,
    SourceSchemaFieldRow,
    StandardizedIndicatorFactRow,
)
from margin.data.ingestion import DataWarehouseIngestionStack
from margin.data.sync_models import DataSyncStatus
from margin.data.warehouse_repository import CanonicalQuery
from margin.storage.base import Base
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)

DECISION = datetime(2026, 6, 22, tzinfo=UTC)


class FakeDailyBarProvider:
    """Provider double with the same daily bar method shape as AKShare/Tushare."""

    name = "fake_provider"

    def get_bars(
        self,
        symbols: list[str],
        start: datetime,
        end: datetime,
        frequency: str = "1d",
    ) -> list[dict]:
        """get bars."""
        assert symbols == ["000001.SZ"]
        assert start == DECISION
        assert end == DECISION
        return [
            {
                "symbol": "000001.SZ",
                "date": DECISION,
                "open": 9.5,
                "high": 10.5,
                "low": 9.0,
                "close": 10.0,
                "volume": 1000,
                "amount": 10000,
                "frequency": frequency,
                "fetched_at": DECISION,
                "available_at": DECISION,
                "source": self.name,
            }
        ]


@pytest.fixture
def data_stack(database_url: str, tmp_path):
    """Provision a clean data warehouse stack."""
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    with session_factory.begin() as session:
        session.query(CanonicalIndicatorValueRow).delete()
        session.query(StandardizedIndicatorFactRow).delete()
        session.query(SourceSchemaFieldRow).delete()
        session.query(RawDataSnapshotRow).delete()
        session.query(DataSyncWorkItemRow).delete()
        session.query(DataSyncRunRow).delete()
        session.query(ProviderEndpointRow).delete()
    yield DataWarehouseIngestionStack(
        session_factory=session_factory,
        snapshot_root=tmp_path,
    )
    engine.dispose()


def test_provider_payload_reaches_canonical_value(data_stack: DataWarehouseIngestionStack) -> None:
    """provider payload reaches canonical value."""
    result = data_stack.sync_daily_bars(
        FakeDailyBarProvider(),
        symbols=("000001.SZ",),
        start=DECISION,
        end=DECISION,
        decision_at=DECISION,
    )

    values = data_stack.warehouse.canonical_values(
        CanonicalQuery(
            security_ids=("000001.SZ",),
            indicator_ids=("close",),
            decision_at=DECISION,
        )
    )

    assert result.status == DataSyncStatus.SUCCEEDED
    assert result.raw_snapshot_ids
    assert result.fact_count == 6
    assert result.canonical_count == 6
    assert values[0].numeric_value == Decimal("10.0000000000")
