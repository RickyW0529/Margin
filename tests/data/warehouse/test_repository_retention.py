"""PIT warehouse repository and reference-aware retention tests."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from margin.data.db_models import (
    CanonicalIndicatorValueRow,
    DataFreshnessStateRow,
    ProviderEndpointRow,
    RawDataSnapshotRow,
    RetentionDeletionAuditRow,
    StandardizedIndicatorFactRow,
)
from margin.data.freshness import DataDomain
from margin.data.retention import RetentionCandidate, SQLAlchemyRetentionService
from margin.data.warehouse_repository import (
    CanonicalQuery,
    PITQueryError,
    SQLAlchemyWarehouseRepository,
)
from margin.storage.base import Base
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)

DECISION = datetime(2026, 6, 22, tzinfo=UTC)


@pytest.fixture
def warehouse_stack(database_url: str):
    """Provide a clean warehouse repository and session factory.

    Args:
        database_url: str: .

    Yields:
        Any: .
    """
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    with session_factory.begin() as session:
        session.query(RetentionDeletionAuditRow).delete()
        session.query(CanonicalIndicatorValueRow).delete()
        session.query(StandardizedIndicatorFactRow).delete()
        session.query(RawDataSnapshotRow).delete()
    yield (
        SQLAlchemyWarehouseRepository(session_factory),
        SQLAlchemyRetentionService(session_factory),
        session_factory,
    )
    with session_factory.begin() as session:
        session.query(RetentionDeletionAuditRow).delete()
        session.query(CanonicalIndicatorValueRow).delete()
        session.query(StandardizedIndicatorFactRow).delete()
        session.query(RawDataSnapshotRow).delete()
    engine.dispose()


def test_historical_query_requires_decision_at(warehouse_stack) -> None:
    """Test that a canonical query without a decision_at raises a PIT error.

    Args:
        warehouse_stack: Any: .

    Returns:
        None: .
    """
    repository, _, _ = warehouse_stack

    with pytest.raises(PITQueryError):
        repository.canonical_values(CanonicalQuery(security_ids=("SEC-1",)))


def test_freshness_filters_by_endpoint_domain_and_keeps_latest(
    warehouse_stack,
) -> None:
    """Readiness sees the latest state for requested data domains only.

    Args:
        warehouse_stack: Any: .

    Returns:
        None: .
    """
    repository, _, session_factory = warehouse_stack
    with session_factory.begin() as session:
        session.query(DataFreshnessStateRow).filter_by(provider="freshness-test").delete()
        session.query(ProviderEndpointRow).filter_by(provider="freshness-test").delete()
        session.add_all(
            [
                ProviderEndpointRow(
                    endpoint_id="freshness-test:daily_bar",
                    provider="freshness-test",
                    code="daily_bar",
                    domain="market",
                    enabled=True,
                    backfill_policy={},
                    revision_lookback_days=1,
                    rate_limit_policy={},
                    schema_version="v1",
                    created_at=DECISION,
                    updated_at=DECISION,
                ),
                ProviderEndpointRow(
                    endpoint_id="freshness-test:filing",
                    provider="freshness-test",
                    code="filing",
                    domain="filing",
                    enabled=True,
                    backfill_policy={},
                    revision_lookback_days=1,
                    rate_limit_policy={},
                    schema_version="v1",
                    created_at=DECISION,
                    updated_at=DECISION,
                ),
                DataFreshnessStateRow(
                    freshness_id="freshness-market-old",
                    provider="freshness-test",
                    endpoint_code="daily_bar",
                    as_of_date=date(2026, 6, 21),
                    expected_at=DECISION - timedelta(days=1),
                    observed_at=DECISION - timedelta(days=1),
                    status="stale",
                    lag_seconds=60,
                    created_at=DECISION,
                ),
                DataFreshnessStateRow(
                    freshness_id="freshness-market-new",
                    provider="freshness-test",
                    endpoint_code="daily_bar",
                    as_of_date=date(2026, 6, 22),
                    expected_at=DECISION,
                    observed_at=DECISION,
                    status="fresh",
                    lag_seconds=0,
                    created_at=DECISION,
                ),
                DataFreshnessStateRow(
                    freshness_id="freshness-filing",
                    provider="freshness-test",
                    endpoint_code="filing",
                    as_of_date=date(2026, 6, 22),
                    expected_at=DECISION,
                    observed_at=DECISION,
                    status="fresh",
                    lag_seconds=0,
                    created_at=DECISION,
                ),
            ]
        )

    records = repository.freshness({DataDomain.MARKET})

    selected = [record for record in records if record.provider == "freshness-test"]
    assert len(selected) == 1
    assert selected[0].endpoint_code == "daily_bar"
    assert selected[0].as_of_date == date(2026, 6, 22)


def test_canonical_query_does_not_return_future_decision(warehouse_stack) -> None:
    """Test that canonical values available after the decision time are excluded.

    Args:
        warehouse_stack: Any: .

    Returns:
        None: .
    """
    repository, _, session_factory = warehouse_stack
    _insert_fact_and_canonical(session_factory, canonical_id="cv-old", value=Decimal("10.00"))
    _insert_fact_and_canonical(
        session_factory,
        canonical_id="cv-future",
        fact_id="fact-future",
        raw_snapshot_id="raw-future",
        value=Decimal("99.00"),
        decision_at=DECISION + timedelta(days=1),
    )

    values = repository.canonical_values(
        CanonicalQuery(
            security_ids=("SEC-1",),
            indicator_ids=("close",),
            decision_at=DECISION,
        )
    )

    assert len(values) == 1
    assert values[0].canonical_id == "cv-old"
    assert values[0].numeric_value == Decimal("10.0000000000")


def test_retention_never_deletes_referenced_raw_snapshot(warehouse_stack) -> None:
    """Test that a raw snapshot referenced by a fact is protected from retention deletion.

    Args:
        warehouse_stack: Any: .

    Returns:
        None: .
    """
    _, retention, session_factory = warehouse_stack
    _insert_fact_and_canonical(session_factory, canonical_id="cv-retained", value=Decimal("10.00"))

    result = retention.delete_expired(
        [
            RetentionCandidate(
                object_type="raw_snapshot",
                object_id="raw-1",
                expires_at=DECISION - timedelta(days=1),
            )
        ],
        now=DECISION,
    )

    assert result.deleted == ()
    assert result.protected_count == 1
    with session_factory() as session:
        assert session.get(RawDataSnapshotRow, "raw-1") is not None
        audits = session.query(RetentionDeletionAuditRow).all()
    assert len(audits) == 1
    assert audits[0].decision == "protected"


def _insert_fact_and_canonical(
    session_factory,
    *,
    canonical_id: str,
    value: Decimal,
    fact_id: str = "fact-1",
    raw_snapshot_id: str = "raw-1",
    decision_at: datetime = DECISION,
) -> None:
    """Insert a raw snapshot, fact, and canonical value row for testing.

    Args:
        session_factory: Any: .
        canonical_id: str: .
        value: Decimal: .
        fact_id: str: .
        raw_snapshot_id: str: .
        decision_at: datetime: .

    Returns:
        None: .
    """
    with session_factory.begin() as session:
        session.add(
            RawDataSnapshotRow(
                snapshot_id=raw_snapshot_id,
                provider="akshare",
                endpoint_code="daily_bar",
                payload_hash=f"sha256:{raw_snapshot_id}",
                storage_uri=f"snapshot://{raw_snapshot_id}",
                compression="zstd",
                raw_size=128,
                compressed_size=64,
                fetched_at=DECISION,
                available_at=DECISION,
                retention_class="hot",
                payload_metadata={},
            )
        )
        session.flush()
        session.add(
            StandardizedIndicatorFactRow(
                fact_id=fact_id,
                provider="akshare",
                provider_fact_id=f"{fact_id}-provider",
                endpoint_code="daily_bar",
                security_id="SEC-1",
                indicator_id="close",
                indicator_version="indicator-v0.2.0",
                event_at=DECISION,
                available_at=DECISION,
                fetched_at=DECISION,
                numeric_value=value,
                unit="CNY",
                quality_score=Decimal("0.90000"),
                mapping_version="mapping-v0.2.0",
                raw_snapshot_id=raw_snapshot_id,
                lineage={},
            )
        )
        session.flush()
        session.add(
            CanonicalIndicatorValueRow(
                canonical_id=canonical_id,
                security_id="SEC-1",
                indicator_id="close",
                indicator_version="indicator-v0.2.0",
                decision_at=decision_at,
                selected_fact_id=fact_id,
                candidate_fact_ids=[fact_id],
                status="resolved",
                numeric_value=value,
                confidence=Decimal("0.90000"),
                resolver_version="resolver-v0.2.0",
                resolver_hash=f"hash-{canonical_id}",
                created_at=decision_at,
            )
        )
