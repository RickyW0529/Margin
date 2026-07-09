"""Repositories for v1 Context Engineering persistence."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from margin.agents.context.db_models import (
    ArtifactLineageEdgeRow,
    ContextFactRow,
    ContextOmissionRow,
    ContextPackRow,
    DomainContextCapsuleRow,
)
from margin.agents.protocol.models import (
    ContextFact,
    ContextOmission,
    ContextPack,
    DomainContextCapsule,
)


@dataclass(frozen=True)
class ContextLineageEdge:
    """One stored context lineage edge."""

    run_id: str
    from_ref: str
    to_ref: str
    edge_type: str
    created_at: datetime


class ContextRepository(Protocol):
    """Persistence boundary for ContextPack, capsule, and lineage records."""

    def save_context_pack(self, pack: ContextPack) -> None:
        """Persist a ContextPack and its queryable facts/omissions."""

    def get_context_pack(self, context_pack_id: str) -> ContextPack | None:
        """Return a ContextPack by id."""

    def list_context_facts(self, context_pack_id: str) -> list[ContextFact]:
        """Return facts belonging to a ContextPack."""

    def list_context_omissions(self, context_pack_id: str) -> list[ContextOmission]:
        """Return omissions belonging to a ContextPack."""

    def save_domain_capsule(
        self,
        capsule: DomainContextCapsule,
        *,
        domain_task_id: str,
        expert_agent: str,
        output_artifact_refs: tuple[str, ...] = (),
        audit_report_ref: str | None = None,
        token_estimate: int = 0,
    ) -> None:
        """Persist one compressed domain context capsule."""

    def get_domain_capsule(self, capsule_id: str) -> DomainContextCapsule | None:
        """Return a domain capsule by id."""

    def record_lineage_edge(
        self,
        *,
        run_id: str,
        from_ref: str,
        to_ref: str,
        edge_type: str,
    ) -> None:
        """Persist one idempotent lineage edge."""

    def list_lineage_edges(self, run_id: str) -> list[ContextLineageEdge]:
        """Return lineage edges for one run."""


class MemoryContextRepository:
    """In-memory ContextRepository used by deterministic tests."""

    def __init__(self) -> None:
        """Initialize empty context stores."""
        self._packs: dict[str, ContextPack] = {}
        self._capsules: dict[str, DomainContextCapsule] = {}
        self._edges: dict[tuple[str, str, str], ContextLineageEdge] = {}

    def save_context_pack(self, pack: ContextPack) -> None:
        """Persist a ContextPack in memory."""
        current = self._packs.get(pack.context_pack_id)
        if current is not None and current != pack:
            raise ValueError(f"context pack '{pack.context_pack_id}' is immutable")
        self._packs[pack.context_pack_id] = pack

    def get_context_pack(self, context_pack_id: str) -> ContextPack | None:
        """Return a ContextPack by id."""
        return self._packs.get(context_pack_id)

    def list_context_facts(self, context_pack_id: str) -> list[ContextFact]:
        """Return facts belonging to a ContextPack."""
        pack = self._packs.get(context_pack_id)
        return list(pack.facts) if pack is not None else []

    def list_context_omissions(self, context_pack_id: str) -> list[ContextOmission]:
        """Return omissions belonging to a ContextPack."""
        pack = self._packs.get(context_pack_id)
        return list(pack.omissions) if pack is not None else []

    def save_domain_capsule(
        self,
        capsule: DomainContextCapsule,
        *,
        domain_task_id: str,
        expert_agent: str,
        output_artifact_refs: tuple[str, ...] = (),
        audit_report_ref: str | None = None,
        token_estimate: int = 0,
    ) -> None:
        """Persist a domain capsule in memory."""
        del domain_task_id, expert_agent, output_artifact_refs, audit_report_ref, token_estimate
        current = self._capsules.get(capsule.capsule_id)
        if current is not None and current != capsule:
            raise ValueError(f"domain capsule '{capsule.capsule_id}' is immutable")
        self._capsules[capsule.capsule_id] = capsule

    def get_domain_capsule(self, capsule_id: str) -> DomainContextCapsule | None:
        """Return a domain capsule by id."""
        return self._capsules.get(capsule_id)

    def record_lineage_edge(
        self,
        *,
        run_id: str,
        from_ref: str,
        to_ref: str,
        edge_type: str,
    ) -> None:
        """Persist one idempotent lineage edge in memory."""
        key = (from_ref, to_ref, edge_type)
        self._edges.setdefault(
            key,
            ContextLineageEdge(
                run_id=run_id,
                from_ref=from_ref,
                to_ref=to_ref,
                edge_type=edge_type,
                created_at=datetime.now(UTC),
            ),
        )

    def list_lineage_edges(self, run_id: str) -> list[ContextLineageEdge]:
        """Return lineage edges for one run."""
        return [edge for edge in self._edges.values() if edge.run_id == run_id]


class SQLAlchemyContextRepository:
    """SQLAlchemy-backed ContextRepository."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        """Initialize repository with a session factory."""
        self._session_factory = session_factory

    def save_context_pack(self, pack: ContextPack) -> None:
        """Persist a ContextPack and its queryable facts/omissions."""
        pack_json = pack.model_dump(mode="json")
        with self._session_factory() as session, session.begin():
            current = session.get(ContextPackRow, pack.context_pack_id)
            if current is not None:
                if current.pack_json != pack_json:
                    raise ValueError(f"context pack '{pack.context_pack_id}' is immutable")
                return
            now = datetime.now(UTC)
            session.add(
                ContextPackRow(
                    context_pack_id=pack.context_pack_id,
                    run_id=pack.run_id,
                    scope=pack.purpose,
                    created_for_agent=pack.target_agent,
                    user_goal=pack_json.get("user_goal", ""),
                    token_budget=pack.token_budget,
                    policy_snapshot_ref=pack_json.get("policy_snapshot_ref"),
                    pack_json=pack_json,
                    pack_hash=pack.payload_hash,
                    created_at=now,
                )
            )
            for fact in pack.facts:
                session.add(_fact_row(pack.context_pack_id, fact, now))
            for omission in pack.omissions:
                session.add(_omission_row(pack.context_pack_id, omission, now))

    def get_context_pack(self, context_pack_id: str) -> ContextPack | None:
        """Return a ContextPack by id."""
        with self._session_factory() as session:
            row = session.get(ContextPackRow, context_pack_id)
            return ContextPack.model_validate(row.pack_json) if row else None

    def list_context_facts(self, context_pack_id: str) -> list[ContextFact]:
        """Return facts belonging to a ContextPack."""
        with self._session_factory() as session:
            rows = session.scalars(
                select(ContextFactRow)
                .where(ContextFactRow.context_pack_id == context_pack_id)
                .order_by(ContextFactRow.fact_id.asc())
            ).all()
            return [_fact_from_row(row) for row in rows]

    def list_context_omissions(self, context_pack_id: str) -> list[ContextOmission]:
        """Return omissions belonging to a ContextPack."""
        with self._session_factory() as session:
            rows = session.scalars(
                select(ContextOmissionRow)
                .where(ContextOmissionRow.context_pack_id == context_pack_id)
                .order_by(ContextOmissionRow.omission_id.asc())
            ).all()
            return [
                ContextOmission(
                    omitted_ref=row.omitted_ref,
                    reason=row.reason,
                    summary=row.summary,
                )
                for row in rows
            ]

    def save_domain_capsule(
        self,
        capsule: DomainContextCapsule,
        *,
        domain_task_id: str,
        expert_agent: str,
        output_artifact_refs: tuple[str, ...] = (),
        audit_report_ref: str | None = None,
        token_estimate: int = 0,
    ) -> None:
        """Persist one compressed domain context capsule."""
        capsule_json = capsule.model_dump(mode="json")
        with self._session_factory() as session, session.begin():
            current = session.get(DomainContextCapsuleRow, capsule.capsule_id)
            if current is not None:
                if current.capsule_json != capsule_json:
                    raise ValueError(f"domain capsule '{capsule.capsule_id}' is immutable")
                return
            session.add(
                DomainContextCapsuleRow(
                    capsule_id=capsule.capsule_id,
                    run_id=capsule.run_id,
                    domain_task_id=domain_task_id,
                    expert_agent=expert_agent,
                    domain=capsule.domain,
                    capsule_json=capsule_json,
                    capsule_hash=capsule.payload_hash,
                    output_artifact_refs=list(output_artifact_refs),
                    audit_report_ref=audit_report_ref,
                    token_estimate=token_estimate,
                    created_at=datetime.now(UTC),
                )
            )

    def get_domain_capsule(self, capsule_id: str) -> DomainContextCapsule | None:
        """Return a domain capsule by id."""
        with self._session_factory() as session:
            row = session.get(DomainContextCapsuleRow, capsule_id)
            return DomainContextCapsule.model_validate(row.capsule_json) if row else None

    def record_lineage_edge(
        self,
        *,
        run_id: str,
        from_ref: str,
        to_ref: str,
        edge_type: str,
    ) -> None:
        """Persist one idempotent lineage edge."""
        with self._session_factory() as session, session.begin():
            existing = session.scalars(
                select(ArtifactLineageEdgeRow).where(
                    ArtifactLineageEdgeRow.from_ref == from_ref,
                    ArtifactLineageEdgeRow.to_ref == to_ref,
                    ArtifactLineageEdgeRow.edge_type == edge_type,
                )
            ).first()
            if existing is not None:
                return
            session.add(
                ArtifactLineageEdgeRow(
                    run_id=run_id,
                    from_ref=from_ref,
                    to_ref=to_ref,
                    edge_type=edge_type,
                    created_at=datetime.now(UTC),
                )
            )

    def list_lineage_edges(self, run_id: str) -> list[ContextLineageEdge]:
        """Return lineage edges for one run."""
        with self._session_factory() as session:
            rows = session.scalars(
                select(ArtifactLineageEdgeRow)
                .where(ArtifactLineageEdgeRow.run_id == run_id)
                .order_by(ArtifactLineageEdgeRow.edge_id.asc())
            ).all()
            return [
                ContextLineageEdge(
                    run_id=row.run_id,
                    from_ref=row.from_ref,
                    to_ref=row.to_ref,
                    edge_type=row.edge_type,
                    created_at=row.created_at,
                )
                for row in rows
            ]


def _fact_row(context_pack_id: str, fact: ContextFact, now: datetime) -> ContextFactRow:
    """Convert a ContextFact into an ORM row."""
    return ContextFactRow(
        fact_id=fact.fact_id,
        context_pack_id=context_pack_id,
        fact_type=fact.fact_type,
        subject_type=fact.subject_type,
        subject_id=fact.subject_id,
        statement=fact.statement,
        value_json=fact.value_json,
        as_of_date=fact.as_of_date,
        valid_from=fact.valid_from,
        valid_to=fact.valid_to,
        available_at=fact.available_at,
        confidence=fact.confidence,
        artifact_refs=list(fact.artifact_refs),
        evidence_refs=list(fact.evidence_refs),
        source_refs=list(fact.source_refs),
        source_locators=list(fact.source_locators),
        freshness_status=fact.freshness_status,
        pii_or_secret_risk=fact.pii_or_secret_risk,
        valid_at=fact.valid_at,
        created_at=now,
    )


def _fact_from_row(row: ContextFactRow) -> ContextFact:
    """Convert an ORM row back into a ContextFact."""
    return ContextFact(
        fact_id=row.fact_id,
        fact_type=row.fact_type,
        subject_type=row.subject_type,
        subject_id=row.subject_id,
        statement=row.statement,
        value_json=row.value_json,
        as_of_date=row.as_of_date,
        valid_from=row.valid_from,
        valid_to=row.valid_to,
        available_at=row.available_at,
        confidence=float(row.confidence),
        artifact_refs=tuple(row.artifact_refs),
        evidence_refs=tuple(row.evidence_refs),
        source_refs=tuple(row.source_refs),
        source_locators=tuple(row.source_locators),
        freshness_status=row.freshness_status,
        pii_or_secret_risk=row.pii_or_secret_risk,
        valid_at=row.valid_at,
    )


def _omission_row(
    context_pack_id: str,
    omission: ContextOmission,
    now: datetime,
) -> ContextOmissionRow:
    """Convert a ContextOmission into an ORM row."""
    return ContextOmissionRow(
        context_pack_id=context_pack_id,
        omitted_ref=omission.omitted_ref,
        reason=omission.reason,
        summary=omission.summary,
        created_at=now,
    )
