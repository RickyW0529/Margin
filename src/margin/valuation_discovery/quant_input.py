"""Quant input snapshot builder.

This module is intentionally provider-free. It reads PIT-safe warehouse facts
through a small protocol and writes frozen valuation-discovery snapshots.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from margin.valuation_discovery.models import DataStatus, QuantInputSnapshot
from margin.valuation_discovery.scope import ScopeBinding


def _normalize_datetime(value: datetime) -> datetime:
    """normalize datetime."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@dataclass(frozen=True)
class CanonicalFactRef:
    """Minimal lineage reference to a PIT-safe canonical warehouse fact."""

    fact_id: str
    security_id: str
    indicator_id: str
    available_at: datetime
    payload_hash: str


class QuantWarehouseRepository(Protocol):
    """Warehouse boundary consumed by QuantInputSnapshotBuilder."""

    def get_latest_fact(
        self,
        *,
        security_id: str,
        indicator_id: str,
        known_at: datetime,
    ) -> CanonicalFactRef | None:
        """Return latest fact available at known_at, or None if unavailable."""

    def get_latest_facts(
        self,
        *,
        security_ids: tuple[str, ...],
        indicator_ids: tuple[str, ...],
        known_at: datetime,
    ) -> tuple[CanonicalFactRef, ...]:
        """Batch-return latest facts for a complete quant input request."""


class QuantInputSnapshotRepository(Protocol):
    """Persistence boundary for quant input snapshots."""

    def add_quant_input_snapshot(self, snapshot: QuantInputSnapshot) -> None:
        """Persist a frozen quant input snapshot."""

    def get_quant_input_snapshot(
        self,
        snapshot_id: str,
    ) -> QuantInputSnapshot | None:
        """Return one frozen quant input snapshot."""


class QuantInputSnapshotBuilder:
    """Build and persist frozen PIT-safe quant input snapshots."""

    def __init__(
        self,
        repository: QuantInputSnapshotRepository,
        warehouse_repository: QuantWarehouseRepository,
    ) -> None:
        """init  ."""
        self._repository = repository
        self._warehouse_repository = warehouse_repository

    def build(
        self,
        *,
        scope: ScopeBinding,
        decision_at: datetime,
        market_window_days: int,
        persist: bool = True,
    ) -> QuantInputSnapshot:
        """Build a frozen snapshot from scope and warehouse facts.

        Invalid snapshots are still persisted for auditability. Downstream quant
        services decide whether a snapshot can be used for publishable results.
        """
        decision = _normalize_datetime(decision_at)
        market_window_start = decision - timedelta(days=market_window_days)
        indicator_ids = tuple(
            dict.fromkeys(
                (
                    *scope.quant_feature_set.required_indicators,
                    *scope.quant_feature_set.optional_indicators,
                )
            )
        )

        fact_refs = self._load_fact_refs(
            security_ids=scope.universe_snapshot.security_ids,
            indicator_ids=indicator_ids,
            known_at=decision,
        )
        fact_by_key = {
            (fact.security_id, fact.indicator_id): fact for fact in fact_refs
        }
        missing_counts = {
            indicator_id: sum(
                1
                for security_id in scope.universe_snapshot.security_ids
                if (security_id, indicator_id) not in fact_by_key
            )
            for indicator_id in scope.quant_feature_set.required_indicators
        }
        missing_required = {
            indicator_id
            for indicator_id, missing_count in missing_counts.items()
            if missing_count == len(scope.universe_snapshot.security_ids)
        }
        quality_flags = tuple(
            f"partial_missing:{indicator_id}:{missing_count}"
            for indicator_id, missing_count in sorted(missing_counts.items())
            if 0 < missing_count < len(scope.universe_snapshot.security_ids)
        )
        pit_errors: list[str] = []
        legal_fact_refs: list[CanonicalFactRef] = []
        for fact in fact_refs:
            available_at = _normalize_datetime(fact.available_at)
            if available_at > decision:
                pit_errors.append(
                    f"{fact.security_id}:{fact.indicator_id}:future_available_at"
                )
                continue
            legal_fact_refs.append(fact)

        data_status = (
            DataStatus.INSUFFICIENT
            if missing_required
            else DataStatus.PIT_DEGRADED
            if pit_errors
            else DataStatus.OK
        )
        snapshot = QuantInputSnapshot(
            scope_version_id=scope.scope_version_id,
            universe_snapshot_id=scope.universe_snapshot.snapshot_id,
            decision_at=decision,
            known_at=decision,
            security_ids=scope.universe_snapshot.security_ids,
            required_indicators=scope.quant_feature_set.required_indicators,
            optional_indicators=scope.quant_feature_set.optional_indicators,
            quant_feature_set=scope.quant_feature_set,
            user_indicator_view=scope.user_indicator_view,
            market_window_start=market_window_start,
            market_window_end=decision,
            fact_refs=tuple(asdict(fact) for fact in legal_fact_refs),
            fact_count=len(legal_fact_refs),
            missing_required=tuple(sorted(missing_required)),
            data_status=data_status,
            quality_flags=quality_flags,
            pit_validation_errors=tuple(pit_errors),
            corporate_action_adjustment_version=scope.corporate_action_adjustment_version,
            industry_snapshot_id=scope.industry_snapshot_id,
        )
        if persist:
            self.persist(snapshot)
        return snapshot

    def persist(self, snapshot: QuantInputSnapshot) -> None:
        """Persist a frozen quant input snapshot."""
        self._repository.add_quant_input_snapshot(snapshot)

    def get(self, snapshot_id: str) -> QuantInputSnapshot | None:
        """Reload a persisted input snapshot for orchestration recovery."""
        getter = getattr(self._repository, "get_quant_input_snapshot", None)
        if not callable(getter):
            raise RuntimeError("quant input repository does not support recovery")
        return getter(snapshot_id)

    def _load_fact_refs(
        self,
        *,
        security_ids: tuple[str, ...],
        indicator_ids: tuple[str, ...],
        known_at: datetime,
    ) -> list[CanonicalFactRef]:
        """Use the production batch boundary with compatibility for test doubles."""
        batch_loader = getattr(
            self._warehouse_repository,
            "get_latest_facts",
            None,
        )
        if callable(batch_loader):
            return list(
                batch_loader(
                    security_ids=security_ids,
                    indicator_ids=indicator_ids,
                    known_at=known_at,
                )
            )
        return [
            fact
            for security_id in security_ids
            for indicator_id in indicator_ids
            if (
                fact := self._warehouse_repository.get_latest_fact(
                    security_id=security_id,
                    indicator_id=indicator_id,
                    known_at=known_at,
                )
            )
            is not None
        ]
