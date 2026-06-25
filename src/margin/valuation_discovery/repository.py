"""Repository contracts for valuation discovery.

Concrete persistence methods are introduced task-by-task. This module exists
early so downstream services can type against a stable repository boundary.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy.orm import Session

from margin.sql.valuation_queries import (
    all_quant_input_snapshot_facts,
    effective_assessment_pointers_for_count,
    effective_assessment_pointers_ordered,
    quant_input_snapshot_facts,
    quant_input_snapshots_ordered,
    valuation_assessment_evidence_by_assessment,
    valuation_assessments_ordered,
)
from margin.valuation_discovery.db_models import (
    EffectiveAssessmentPointerRow,
    QuantInputSnapshotFactRow,
    QuantInputSnapshotRow,
    ValuationAssessmentEvidenceRow,
    ValuationAssessmentRow,
)
from margin.valuation_discovery.models import (
    DataStatus,
    EffectiveAssessmentPointer,
    QuantInputSnapshot,
    UniverseDefinition,
    UniverseMembership,
    UniverseSnapshot,
    ValuationAssessment,
    ValuationAssessmentEvidence,
)


class ValuationDiscoveryRepository(Protocol):
    """Persistence boundary for valuation discovery."""

    def add_universe_membership(self, membership: UniverseMembership) -> None:
        """Persist a bitemporal universe membership."""

    def list_universe_memberships(
        self,
        *,
        universe_code: str | None = None,
    ) -> list[UniverseMembership]:
        """Return universe memberships visible to the repository implementation."""

    def add_universe_snapshot(self, snapshot: UniverseSnapshot) -> None:
        """Persist a frozen universe snapshot."""

    def add_quant_input_snapshot(self, snapshot: QuantInputSnapshot) -> None:
        """Persist a frozen quant input snapshot."""

    def get_quant_input_snapshot(
        self,
        snapshot_id: str,
    ) -> QuantInputSnapshot | None:
        """Return one frozen quant input snapshot by ID."""

    def add_effective_assessment_pointer(
        self,
        pointer: EffectiveAssessmentPointer,
    ) -> None:
        """Persist an effective assessment pointer event."""

    def publish_valuation_result(
        self,
        *,
        assessment: ValuationAssessment | None,
        evidence_edges: tuple[ValuationAssessmentEvidence, ...],
        pointer: EffectiveAssessmentPointer,
    ) -> None:
        """Atomically publish one immutable assessment result."""

    def get_valuation_assessment(
        self,
        assessment_id: str,
    ) -> ValuationAssessment | None:
        """Return one assessment by ID."""

    def count_effective_assessments(
        self,
        *,
        scope_version_id: str,
        as_of: datetime,
    ) -> int:
        """Count latest effective assessment pointers visible as of a time."""


class MemoryValuationDiscoveryRepository:
    """In-memory repository used by unit tests and local composition tests."""

    def __init__(self) -> None:
        """init  ."""
        self._definitions: dict[str, UniverseDefinition] = {}
        self._memberships: dict[str, UniverseMembership] = {}
        self._snapshots: dict[str, UniverseSnapshot] = {}
        self._quant_input_snapshots: dict[str, QuantInputSnapshot] = {}
        self._effective_pointers: dict[str, EffectiveAssessmentPointer] = {}
        self._assessments: dict[str, ValuationAssessment] = {}
        self._assessment_evidence: dict[str, ValuationAssessmentEvidence] = {}

    def add_universe_definition(self, definition: UniverseDefinition) -> None:
        """Persist a universe definition idempotently by definition ID."""
        self._definitions.setdefault(definition.definition_id, definition)

    def list_universe_definitions(self) -> list[UniverseDefinition]:
        """Return all universe definitions sorted by code/name for determinism."""
        return sorted(
            self._definitions.values(),
            key=lambda item: (str(item.universe_code), item.name, item.definition_id),
        )

    def add_universe_membership(self, membership: UniverseMembership) -> None:
        """Persist a bitemporal universe membership."""
        self._memberships[membership.membership_id] = membership

    def list_universe_memberships(
        self,
        *,
        universe_code: str | None = None,
    ) -> list[UniverseMembership]:
        """Return memberships, optionally filtered by universe code."""
        memberships = self._memberships.values()
        if universe_code is not None:
            memberships = [
                membership
                for membership in memberships
                if str(membership.universe_code) == universe_code
            ]
        return sorted(
            memberships,
            key=lambda item: (item.security_id, item.valid_from, item.system_from),
        )

    def add_universe_snapshot(self, snapshot: UniverseSnapshot) -> None:
        """Persist a frozen universe snapshot."""
        self._snapshots[snapshot.snapshot_id] = snapshot

    def list_universe_snapshots(self) -> list[UniverseSnapshot]:
        """Return stored snapshots sorted by creation time."""
        return sorted(self._snapshots.values(), key=lambda item: item.created_at)

    def add_quant_input_snapshot(self, snapshot: QuantInputSnapshot) -> None:
        """Persist a frozen quant input snapshot."""
        self._quant_input_snapshots[snapshot.snapshot_id] = snapshot

    def list_quant_input_snapshots(self) -> list[QuantInputSnapshot]:
        """Return stored quant input snapshots sorted by creation time."""
        return sorted(self._quant_input_snapshots.values(), key=lambda item: item.created_at)

    def get_quant_input_snapshot(
        self,
        snapshot_id: str,
    ) -> QuantInputSnapshot | None:
        """Return one frozen quant input snapshot by ID."""
        return self._quant_input_snapshots.get(snapshot_id)

    def add_effective_assessment_pointer(
        self,
        pointer: EffectiveAssessmentPointer,
    ) -> None:
        """Persist an effective assessment pointer event."""
        existing = self._effective_pointers.get(pointer.pointer_id)
        if existing is not None and existing != pointer:
            raise ValueError("conflicting effective assessment pointer")
        self._effective_pointers.setdefault(pointer.pointer_id, pointer)

    def list_effective_assessment_pointers(self) -> list[EffectiveAssessmentPointer]:
        """Return effective assessment pointer events sorted by creation time."""
        return sorted(self._effective_pointers.values(), key=lambda item: item.created_at)

    def publish_valuation_result(
        self,
        *,
        assessment: ValuationAssessment | None,
        evidence_edges: tuple[ValuationAssessmentEvidence, ...],
        pointer: EffectiveAssessmentPointer,
    ) -> None:
        """Atomically publish one result in the in-memory repository."""
        if assessment is not None:
            existing = self._assessments.get(assessment.assessment_id)
            if existing is not None and existing != assessment:
                raise ValueError("conflicting valuation assessment")
            for edge in evidence_edges:
                existing_edge = self._assessment_evidence.get(edge.edge_id)
                if existing_edge is not None and existing_edge != edge:
                    raise ValueError("conflicting valuation assessment evidence")
            self._assessments.setdefault(assessment.assessment_id, assessment)
            for edge in evidence_edges:
                self._assessment_evidence.setdefault(edge.edge_id, edge)
        self.add_effective_assessment_pointer(pointer)

    def get_valuation_assessment(
        self,
        assessment_id: str,
    ) -> ValuationAssessment | None:
        """Return one assessment by ID."""
        return self._assessments.get(assessment_id)

    def list_valuation_assessments(self) -> list[ValuationAssessment]:
        """Return assessments in deterministic decision order."""
        return sorted(
            self._assessments.values(),
            key=lambda item: (item.decision_at, item.assessment_id),
        )

    def list_valuation_assessment_evidence(
        self,
        assessment_id: str,
    ) -> list[ValuationAssessmentEvidence]:
        """Return evidence edges for one assessment."""
        return sorted(
            (
                edge
                for edge in self._assessment_evidence.values()
                if edge.assessment_id == assessment_id
            ),
            key=lambda edge: (edge.evidence_id, edge.edge_id),
        )

    def count_effective_assessments(
        self,
        *,
        scope_version_id: str,
        as_of: datetime,
    ) -> int:
        """Count latest visible pointers per security."""
        latest: dict[str, EffectiveAssessmentPointer] = {}
        for pointer in self._effective_pointers.values():
            if (
                pointer.scope_version_id != scope_version_id
                or pointer.effective_from > as_of
            ):
                continue
            current = latest.get(pointer.security_id)
            if current is None or (
                pointer.effective_from,
                pointer.created_at,
                pointer.pointer_id,
            ) > (
                current.effective_from,
                current.created_at,
                current.pointer_id,
            ):
                latest[pointer.security_id] = pointer
        return len(latest)


class SQLAlchemyValuationDiscoveryRepository:
    """PostgreSQL-backed valuation discovery repository."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        """init  ."""
        self._session_factory = session_factory

    def add_quant_input_snapshot(self, snapshot: QuantInputSnapshot) -> None:
        """Persist a quant input snapshot and its fact lineage in one transaction."""
        with self._session_factory.begin() as session:
            session.add(_quant_input_snapshot_to_row(snapshot))
            for index, fact_ref in enumerate(snapshot.fact_refs):
                session.add(_quant_input_fact_to_row(snapshot.snapshot_id, index, fact_ref))

    def list_quant_input_snapshots(self) -> list[QuantInputSnapshot]:
        """Return persisted quant input snapshots ordered by creation time."""
        with self._session_factory() as session:
            rows = session.scalars(
                quant_input_snapshots_ordered()
            ).all()
            facts_by_snapshot: dict[str, list[QuantInputSnapshotFactRow]] = {}
            for fact in session.scalars(all_quant_input_snapshot_facts()).all():
                facts_by_snapshot.setdefault(fact.snapshot_id, []).append(fact)
        return [
            _quant_input_snapshot_from_row(row, facts_by_snapshot.get(row.snapshot_id, []))
            for row in rows
        ]

    def get_quant_input_snapshot(
        self,
        snapshot_id: str,
    ) -> QuantInputSnapshot | None:
        """Return one frozen quant input snapshot with its fact lineage."""
        with self._session_factory() as session:
            row = session.get(QuantInputSnapshotRow, snapshot_id)
            if row is None:
                return None
            facts = session.scalars(
                quant_input_snapshot_facts(snapshot_id)
            ).all()
        return _quant_input_snapshot_from_row(row, list(facts))

    def add_effective_assessment_pointer(
        self,
        pointer: EffectiveAssessmentPointer,
    ) -> None:
        """Persist an effective assessment pointer event."""
        with self._session_factory.begin() as session:
            _persist_pointer(session, pointer)

    def list_effective_assessment_pointers(self) -> list[EffectiveAssessmentPointer]:
        """Return effective assessment pointer events ordered by creation time."""
        with self._session_factory() as session:
            rows = session.scalars(
                effective_assessment_pointers_ordered()
            ).all()
        return [_effective_pointer_from_row(row) for row in rows]

    def publish_valuation_result(
        self,
        *,
        assessment: ValuationAssessment | None,
        evidence_edges: tuple[ValuationAssessmentEvidence, ...],
        pointer: EffectiveAssessmentPointer,
    ) -> None:
        """Atomically persist assessment, evidence edges, and pointer."""
        with self._session_factory.begin() as session:
            if assessment is not None:
                _persist_assessment(session, assessment)
                for edge in evidence_edges:
                    _persist_assessment_evidence(session, edge)
            _persist_pointer(session, pointer)

    def get_valuation_assessment(
        self,
        assessment_id: str,
    ) -> ValuationAssessment | None:
        """Return one persisted assessment by ID."""
        with self._session_factory() as session:
            row = session.get(ValuationAssessmentRow, assessment_id)
            return _valuation_assessment_from_row(row) if row is not None else None

    def list_valuation_assessments(self) -> list[ValuationAssessment]:
        """Return assessments ordered by decision time."""
        with self._session_factory() as session:
            rows = session.scalars(
                valuation_assessments_ordered()
            ).all()
        return [_valuation_assessment_from_row(row) for row in rows]

    def list_valuation_assessment_evidence(
        self,
        assessment_id: str,
    ) -> list[ValuationAssessmentEvidence]:
        """Return evidence edges for one assessment."""
        with self._session_factory() as session:
            rows = session.scalars(
                valuation_assessment_evidence_by_assessment(assessment_id)
            ).all()
        return [_valuation_evidence_from_row(row) for row in rows]

    def count_effective_assessments(
        self,
        *,
        scope_version_id: str,
        as_of: datetime,
    ) -> int:
        """Count latest visible pointers per security."""
        with self._session_factory() as session:
            rows = session.scalars(
                effective_assessment_pointers_for_count(scope_version_id, as_of)
            ).all()
        return len({row.security_id for row in rows})


def _quant_input_snapshot_to_row(snapshot: QuantInputSnapshot) -> QuantInputSnapshotRow:
    """quant input snapshot to row."""
    return QuantInputSnapshotRow(
        snapshot_id=snapshot.snapshot_id,
        scope_version_id=snapshot.scope_version_id,
        universe_snapshot_id=snapshot.universe_snapshot_id,
        decision_at=snapshot.decision_at,
        known_at=snapshot.known_at,
        security_ids=list(snapshot.security_ids),
        required_indicators=list(snapshot.required_indicators),
        optional_indicators=list(snapshot.optional_indicators),
        quant_feature_set_version_id=getattr(snapshot.quant_feature_set, "version_id", None),
        user_indicator_view_version_id=getattr(snapshot.user_indicator_view, "version_id", None),
        feature_snapshot_id=snapshot.feature_snapshot_id,
        market_window_start=snapshot.market_window_start,
        market_window_end=snapshot.market_window_end,
        fact_count=snapshot.fact_count,
        missing_required=list(snapshot.missing_required),
        data_status=snapshot.data_status.value,
        quality_flags=list(snapshot.quality_flags),
        freshness_flags=list(snapshot.freshness_flags),
        pit_validation_errors=list(snapshot.pit_validation_errors),
        corporate_action_adjustment_version=snapshot.corporate_action_adjustment_version,
        industry_snapshot_id=snapshot.industry_snapshot_id,
        input_hash=snapshot.input_hash,
        created_at=snapshot.created_at,
    )


def _quant_input_fact_to_row(
    snapshot_id: str,
    index: int,
    fact_ref: dict[str, Any],
) -> QuantInputSnapshotFactRow:
    """quant input fact to row."""
    unique_material = f"{snapshot_id}:{index}:{fact_ref['fact_id']}:{fact_ref['indicator_id']}"
    fact_ref_id = "qisf_" + hashlib.sha256(unique_material.encode("utf-8")).hexdigest()[:24]
    return QuantInputSnapshotFactRow(
        fact_ref_id=fact_ref_id,
        snapshot_id=snapshot_id,
        security_id=str(fact_ref["security_id"]),
        indicator_code=str(fact_ref["indicator_id"]),
        fact_id=str(fact_ref["fact_id"]),
        available_at=_parse_datetime(fact_ref["available_at"]),
        payload_hash=str(fact_ref["payload_hash"]),
    )


def _quant_input_snapshot_from_row(
    row: QuantInputSnapshotRow,
    fact_rows: list[QuantInputSnapshotFactRow],
) -> QuantInputSnapshot:
    """quant input snapshot from row."""
    return QuantInputSnapshot(
        snapshot_id=row.snapshot_id,
        scope_version_id=row.scope_version_id,
        universe_snapshot_id=row.universe_snapshot_id,
        decision_at=row.decision_at,
        known_at=row.known_at,
        security_ids=tuple(row.security_ids),
        required_indicators=tuple(row.required_indicators),
        optional_indicators=tuple(row.optional_indicators),
        feature_snapshot_id=row.feature_snapshot_id,
        market_window_start=row.market_window_start,
        market_window_end=row.market_window_end,
        fact_refs=tuple(
            {
                "fact_id": fact.fact_id,
                "security_id": fact.security_id,
                "indicator_id": fact.indicator_code,
                "available_at": fact.available_at,
                "payload_hash": fact.payload_hash,
            }
            for fact in fact_rows
        ),
        fact_count=row.fact_count,
        missing_required=tuple(row.missing_required),
        data_status=DataStatus(row.data_status),
        quality_flags=tuple(row.quality_flags),
        freshness_flags=tuple(row.freshness_flags),
        pit_validation_errors=tuple(row.pit_validation_errors),
        corporate_action_adjustment_version=row.corporate_action_adjustment_version,
        industry_snapshot_id=row.industry_snapshot_id,
        input_hash=row.input_hash,
        created_at=row.created_at,
    )


def _parse_datetime(value: Any) -> datetime:
    """parse datetime."""
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    raise TypeError(f"Unsupported datetime value: {type(value).__name__}")


def _effective_pointer_to_row(
    pointer: EffectiveAssessmentPointer,
) -> EffectiveAssessmentPointerRow:
    """effective pointer to row."""
    return EffectiveAssessmentPointerRow(
        pointer_id=pointer.pointer_id,
        security_id=pointer.security_id,
        scope_version_id=pointer.scope_version_id,
        effective_assessment_id=pointer.effective_assessment_id,
        effective_from=pointer.effective_from,
        previous_assessment_id=pointer.previous_assessment_id,
        assessment_freshness=pointer.assessment_freshness,
        stale_reason=pointer.stale_reason,
        last_successful_data_check_at=pointer.last_successful_data_check_at,
        last_successful_news_check_at=pointer.last_successful_news_check_at,
        created_at=pointer.created_at,
    )


def _effective_pointer_from_row(
    row: EffectiveAssessmentPointerRow,
) -> EffectiveAssessmentPointer:
    """effective pointer from row."""
    return EffectiveAssessmentPointer(
        pointer_id=row.pointer_id,
        security_id=row.security_id,
        scope_version_id=row.scope_version_id,
        effective_assessment_id=row.effective_assessment_id,
        effective_from=row.effective_from,
        previous_assessment_id=row.previous_assessment_id,
        assessment_freshness=row.assessment_freshness,
        stale_reason=row.stale_reason,
        last_successful_data_check_at=row.last_successful_data_check_at,
        last_successful_news_check_at=row.last_successful_news_check_at,
        created_at=row.created_at,
    )


def _valuation_assessment_to_row(
    assessment: ValuationAssessment,
) -> ValuationAssessmentRow:
    """Convert an immutable valuation assessment to its database row."""
    return ValuationAssessmentRow(
        assessment_id=assessment.assessment_id,
        security_id=assessment.security_id,
        scope_version_id=assessment.scope_version_id,
        decision_at=assessment.decision_at,
        valuation_model=assessment.valuation_model,
        intrinsic_value=assessment.intrinsic_value,
        margin_of_safety=assessment.margin_of_safety,
        conclusion=assessment.conclusion,
        evidence_refs=list(assessment.evidence_refs),
        created_at=assessment.created_at,
    )


def _valuation_assessment_from_row(
    row: ValuationAssessmentRow,
) -> ValuationAssessment:
    """Convert a valuation assessment row to its immutable model."""
    return ValuationAssessment(
        assessment_id=row.assessment_id,
        security_id=row.security_id,
        scope_version_id=row.scope_version_id,
        decision_at=row.decision_at,
        valuation_model=row.valuation_model,
        intrinsic_value=row.intrinsic_value,
        margin_of_safety=row.margin_of_safety,
        conclusion=row.conclusion,
        evidence_refs=tuple(row.evidence_refs),
        created_at=row.created_at,
    )


def _valuation_evidence_to_row(
    edge: ValuationAssessmentEvidence,
) -> ValuationAssessmentEvidenceRow:
    """Convert an immutable assessment-evidence edge to a row."""
    return ValuationAssessmentEvidenceRow(
        edge_id=edge.edge_id,
        assessment_id=edge.assessment_id,
        evidence_id=edge.evidence_id,
        claim_id=edge.claim_id,
        role=edge.role,
        created_at=edge.created_at,
    )


def _valuation_evidence_from_row(
    row: ValuationAssessmentEvidenceRow,
) -> ValuationAssessmentEvidence:
    """Convert an assessment-evidence row to its immutable model."""
    return ValuationAssessmentEvidence(
        edge_id=row.edge_id,
        assessment_id=row.assessment_id,
        evidence_id=row.evidence_id,
        claim_id=row.claim_id,
        role=row.role,
        created_at=row.created_at,
    )


def _persist_assessment(
    session: Session,
    assessment: ValuationAssessment,
) -> None:
    """Persist one assessment idempotently or reject conflicting replay."""
    existing = session.get(ValuationAssessmentRow, assessment.assessment_id)
    if existing is not None:
        if _valuation_assessment_from_row(existing) != assessment:
            raise ValueError("conflicting valuation assessment")
        return
    session.add(_valuation_assessment_to_row(assessment))


def _persist_assessment_evidence(
    session: Session,
    edge: ValuationAssessmentEvidence,
) -> None:
    """Persist one evidence edge idempotently."""
    existing = session.get(ValuationAssessmentEvidenceRow, edge.edge_id)
    if existing is not None:
        if _valuation_evidence_from_row(existing) != edge:
            raise ValueError("conflicting valuation assessment evidence")
        return
    session.add(_valuation_evidence_to_row(edge))


def _persist_pointer(
    session: Session,
    pointer: EffectiveAssessmentPointer,
) -> None:
    """Persist one effective pointer idempotently."""
    existing = session.get(EffectiveAssessmentPointerRow, pointer.pointer_id)
    if existing is not None:
        if _effective_pointer_from_row(existing) != pointer:
            raise ValueError("conflicting effective assessment pointer")
        return
    session.add(_effective_pointer_to_row(pointer))
