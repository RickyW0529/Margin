"""QuantInputSnapshotBuilder tests.

This module validates that the quant input snapshot builder marks snapshots
invalid when required indicators are missing, preserves quant features
regardless of user indicator views, and handles partial company missing
data without aborting the entire universe.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from margin.valuation_discovery.models import DataStatus, UniverseCode, UniverseSnapshot
from margin.valuation_discovery.quant_input import CanonicalFactRef, QuantInputSnapshotBuilder
from margin.valuation_discovery.repository import MemoryValuationDiscoveryRepository
from margin.valuation_discovery.scope import (
    QuantFeatureSet,
    ScopeBinding,
    UserIndicatorView,
)


@dataclass
class FakeWarehouseRepository:
    """Fake warehouse repository for single-fact lookups.."""

    facts: dict[tuple[str, str], CanonicalFactRef]

    def remove_indicator(self, security_id: str, indicator_id: str) -> None:
        """Remove a single fact from the fake warehouse.

        Args:
            security_id: str: .
            indicator_id: str: .

        Returns:
            None: .
        """
        self.facts.pop((security_id, indicator_id), None)

    def get_latest_fact(
        self,
        *,
        security_id: str,
        indicator_id: str,
        known_at: datetime,
    ) -> CanonicalFactRef | None:
        """Return the latest fact for a security-indicator pair known at the given time.

        Args:
            security_id: str: .
            indicator_id: str: .
            known_at: datetime: .

        Returns:
            CanonicalFactRef | None: .
        """
        fact = self.facts.get((security_id, indicator_id))
        if fact is None or fact.available_at > known_at:
            return None
        return fact


@dataclass
class BatchWarehouseRepository:
    """Batch warehouse double used to verify full-universe snapshot loading.."""

    facts: tuple[CanonicalFactRef, ...]
    calls: int = 0

    def get_latest_facts(
        self,
        *,
        security_ids: tuple[str, ...],
        indicator_ids: tuple[str, ...],
        known_at: datetime,
    ) -> tuple[CanonicalFactRef, ...]:
        """Return all current refs through one batched call, asserting expected inputs.

        Args:
            security_ids: tuple[str, ...]: .
            indicator_ids: tuple[str, ...]: .
            known_at: datetime: .

        Returns:
            tuple[CanonicalFactRef, ...]: .
        """
        assert security_ids == ("000001.SZ", "000002.SZ")
        assert indicator_ids == ("roe_ttm",)
        assert known_at == datetime(2026, 6, 22, tzinfo=UTC)
        self.calls += 1
        return self.facts


@pytest.fixture
def valuation_repository() -> MemoryValuationDiscoveryRepository:
    """Return a fresh in-memory valuation discovery repository.

    Returns:
        MemoryValuationDiscoveryRepository: .
    """
    return MemoryValuationDiscoveryRepository()


@pytest.fixture
def universe_snapshot() -> UniverseSnapshot:
    """Return a deterministic CSI300 universe snapshot with one member.

    Returns:
        UniverseSnapshot: .
    """
    return UniverseSnapshot(
        universe_code=UniverseCode.CSI300,
        universe_version_id="univ-v1",
        business_at=datetime(2026, 6, 22, tzinfo=UTC),
        known_at=datetime(2026, 6, 22, tzinfo=UTC),
        security_ids=("000001.SZ",),
        membership_ids=("mem-1",),
    )


@pytest.fixture
def active_scope(universe_snapshot: UniverseSnapshot) -> ScopeBinding:
    """Return a scope binding with all indicators visible.

    Args:
        universe_snapshot: UniverseSnapshot: .

    Returns:
        ScopeBinding: .
    """
    return ScopeBinding(
        scope_version_id="scope-v1",
        universe_snapshot=universe_snapshot,
        quant_feature_set=QuantFeatureSet(
            version_id="qfs-v1",
            required_indicators=("roe_ttm", "pb"),
            optional_indicators=("dividend_yield",),
        ),
        user_indicator_view=UserIndicatorView(
            version_id="view-v1",
            visible_indicator_ids=("roe_ttm", "pb", "dividend_yield"),
        ),
        corporate_action_adjustment_version="adj-v1",
        industry_snapshot_id="industry-v1",
    )


@pytest.fixture
def active_scope_with_view_excluding_pb(universe_snapshot: UniverseSnapshot) -> ScopeBinding:
    """Return a scope binding where the user indicator view excludes pb.

    Args:
        universe_snapshot: UniverseSnapshot: .

    Returns:
        ScopeBinding: .
    """
    return ScopeBinding(
        scope_version_id="scope-v2",
        universe_snapshot=universe_snapshot,
        quant_feature_set=QuantFeatureSet(
            version_id="qfs-v1",
            required_indicators=("roe_ttm", "pb"),
            optional_indicators=("dividend_yield",),
        ),
        user_indicator_view=UserIndicatorView(
            version_id="view-v2",
            visible_indicator_ids=("roe_ttm", "dividend_yield"),
        ),
        corporate_action_adjustment_version="adj-v1",
        industry_snapshot_id="industry-v1",
    )


@pytest.fixture
def warehouse_repository() -> FakeWarehouseRepository:
    """Return a fake warehouse repository with roe_ttm and pb facts.

    Returns:
        FakeWarehouseRepository: .
    """
    return FakeWarehouseRepository(
        facts={
            ("000001.SZ", "roe_ttm"): CanonicalFactRef(
                fact_id="fact-roe",
                security_id="000001.SZ",
                indicator_id="roe_ttm",
                available_at=datetime(2026, 6, 1, tzinfo=UTC),
                payload_hash="sha256:roe",
            ),
            ("000001.SZ", "pb"): CanonicalFactRef(
                fact_id="fact-pb",
                security_id="000001.SZ",
                indicator_id="pb",
                available_at=datetime(2026, 6, 1, tzinfo=UTC),
                payload_hash="sha256:pb",
            ),
        }
    )


def test_quant_input_snapshot_invalid_when_required_indicator_missing(
    valuation_repository: MemoryValuationDiscoveryRepository,
    warehouse_repository: FakeWarehouseRepository,
    active_scope: ScopeBinding,
) -> None:
    """Verify the snapshot is invalid when a required indicator is missing.

    Args:
        valuation_repository: MemoryValuationDiscoveryRepository: .
        warehouse_repository: FakeWarehouseRepository: .
        active_scope: ScopeBinding: .

    Returns:
        None: .
    """
    warehouse_repository.remove_indicator("000001.SZ", "roe_ttm")
    builder = QuantInputSnapshotBuilder(valuation_repository, warehouse_repository)

    snapshot = builder.build(
        scope=active_scope,
        decision_at=datetime(2026, 6, 22, tzinfo=UTC),
        market_window_days=260,
    )

    assert snapshot.is_valid is False
    assert snapshot.data_status == DataStatus.INSUFFICIENT
    assert "roe_ttm" in snapshot.missing_required_indicators
    assert valuation_repository.list_quant_input_snapshots() == [snapshot]


def test_user_indicator_view_does_not_change_quant_features(
    valuation_repository: MemoryValuationDiscoveryRepository,
    warehouse_repository: FakeWarehouseRepository,
    active_scope_with_view_excluding_pb: ScopeBinding,
) -> None:
    """Verify the user indicator view does not change required quant features.

    Args:
        valuation_repository: MemoryValuationDiscoveryRepository: .
        warehouse_repository: FakeWarehouseRepository: .
        active_scope_with_view_excluding_pb: ScopeBinding: .

    Returns:
        None: .
    """
    builder = QuantInputSnapshotBuilder(valuation_repository, warehouse_repository)

    snapshot = builder.build(
        scope=active_scope_with_view_excluding_pb,
        decision_at=datetime(2026, 6, 22, tzinfo=UTC),
        market_window_days=260,
    )

    assert "pb" in snapshot.quant_feature_set.required_indicators
    assert "pb" not in snapshot.user_indicator_view.visible_indicator_ids
    assert snapshot.is_valid is True
    assert snapshot.fact_count == 2
    assert snapshot.market_window_start == datetime(2025, 10, 5, tzinfo=UTC)
    assert snapshot.input_hash.startswith("sha256:")


def test_partial_company_missing_data_does_not_abort_entire_universe(
    valuation_repository: MemoryValuationDiscoveryRepository,
) -> None:
    """Verify per-company missing data is handled by hard filters, not run rejection.

    Args:
        valuation_repository: MemoryValuationDiscoveryRepository: .

    Returns:
        None: .
    """
    universe = UniverseSnapshot(
        universe_code=UniverseCode.CSI300,
        universe_version_id="univ-v2",
        business_at=datetime(2026, 6, 22, tzinfo=UTC),
        known_at=datetime(2026, 6, 22, tzinfo=UTC),
        security_ids=("000001.SZ", "000002.SZ"),
    )
    scope = ScopeBinding(
        scope_version_id="scope-v3",
        universe_snapshot=universe,
        quant_feature_set=QuantFeatureSet(
            version_id="qfs-v2",
            required_indicators=("roe_ttm",),
        ),
        user_indicator_view=UserIndicatorView(
            version_id="view-v3",
            visible_indicator_ids=("roe_ttm",),
        ),
        corporate_action_adjustment_version="adj-v1",
        industry_snapshot_id="industry-v1",
    )
    warehouse = BatchWarehouseRepository(
        facts=(
            CanonicalFactRef(
                fact_id="fact-roe-1",
                security_id="000001.SZ",
                indicator_id="roe_ttm",
                available_at=datetime(2026, 6, 1, tzinfo=UTC),
                payload_hash="sha256:roe-1",
            ),
        )
    )

    snapshot = QuantInputSnapshotBuilder(
        valuation_repository,
        warehouse,
    ).build(
        scope=scope,
        decision_at=datetime(2026, 6, 22, tzinfo=UTC),
        market_window_days=260,
    )

    assert snapshot.is_valid
    assert snapshot.missing_required == ()
    assert snapshot.quality_flags == ("partial_missing:roe_ttm:1",)
    assert warehouse.calls == 1
