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
from margin.data.sync_models import DataSyncStatus, EndpointWorkItem
from margin.data.warehouse_repository import CanonicalQuery, IndicatorHistoryQuery
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
        """Return one daily bar for the requested symbol and date range."""
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
    """Test that a provider payload flows through to a persisted canonical value."""
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


def test_text_indicator_reaches_canonical_value(
    data_stack: DataWarehouseIngestionStack,
) -> None:
    """Audit opinions and status labels remain typed text in the warehouse."""
    item = EndpointWorkItem(
        work_item_id="audit-work",
        run_id="audit-run",
        provider="tushare",
        endpoint_code="fina_audit",
    )

    result = data_stack.ingest_indicator_records(
        item,
        provider="tushare",
        endpoint_code="fina_audit",
        raw_records=[
            {
                "symbol": "000001.SZ",
                "report_date": "20251231",
                "ann_date": "20260420",
                "audit_opinion": "标准无保留意见",
                "fetched_at": DECISION,
                "available_at": "20260420",
                "source": "tushare",
            }
        ],
        decision_at=DECISION,
    )
    values = data_stack.warehouse.canonical_values(
        CanonicalQuery(
            security_ids=("000001.SZ",),
            indicator_ids=("audit_opinion",),
            decision_at=DECISION,
        )
    )

    assert result.fact_count == 1
    assert values[0].text_value == "标准无保留意见"


def test_index_weight_keeps_index_code_metadata(
    data_stack: DataWarehouseIngestionStack,
) -> None:
    """Index constituent facts preserve the owning index code."""
    item = EndpointWorkItem(
        work_item_id="index-weight-work",
        run_id="index-weight-run",
        provider="tushare",
        endpoint_code="index_weight",
    )

    result = data_stack.ingest_indicator_records(
        item,
        provider="tushare",
        endpoint_code="index_weight",
        raw_records=[
            {
                "symbol": "000001.SZ",
                "trade_date": "20260622",
                "index_code": "000905.SH",
                "index_weight": 0.0123,
                "fetched_at": DECISION,
                "available_at": "20260622",
                "source": "tushare",
            }
        ],
        decision_at=DECISION,
    )
    values = data_stack.warehouse.canonical_values(
        CanonicalQuery(
            security_ids=("000001.SZ",),
            indicator_ids=("index_weight",),
            decision_at=DECISION,
        )
    )

    assert result.fact_count == 1
    assert values[0].numeric_value == Decimal("0.0123000000")
    assert values[0].json_value == {"index_code": "000905.SH"}


def test_indicator_history_can_limit_recent_points_per_indicator(
    data_stack: DataWarehouseIngestionStack,
) -> None:
    """Quant history reads can cap per-security points while keeping latest facts."""
    item = EndpointWorkItem(
        work_item_id="history-work",
        run_id="history-run",
        provider="tushare",
        endpoint_code="daily_bar",
    )
    data_stack.ingest_indicator_records(
        item,
        provider="tushare",
        endpoint_code="daily_bar",
        raw_records=[
            {
                "symbol": "000001.SZ",
                "date": f"202606{day:02d}",
                "close": float(day),
                "fetched_at": DECISION,
                "available_at": f"202606{day:02d}",
                "source": "tushare",
            }
            for day in (18, 19, 20)
        ],
        decision_at=DECISION,
    )

    values = data_stack.warehouse.indicator_history(
        IndicatorHistoryQuery(
            security_ids=("000001.SZ",),
            indicator_ids=("close",),
            start_date=datetime(2026, 6, 1, tzinfo=UTC).date(),
            end_date=datetime(2026, 6, 22, tzinfo=UTC).date(),
            decision_at=DECISION,
            max_points_per_indicator=2,
        )
    )

    assert [value.event_at.date().isoformat() for value in values] == [
        "2026-06-19",
        "2026-06-20",
    ]
