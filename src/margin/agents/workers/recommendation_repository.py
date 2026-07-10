"""SQL persistence for immutable recommendation worker artifacts."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from margin.agent_runtime.db_models import RecommendationWorkerArtifactRow
from margin.agents.workers.recommendation_workers import CatalystResearchContext
from margin.core.hashing import stable_json_hash
from margin.storage.database import SessionFactory


class SQLAlchemyRecommendationArtifactRepository:
    """Persist each worker boundary once for durable process-restart recovery."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def save(
        self,
        *,
        artifact_id: str,
        orchestration_run_id: str,
        worker_name: str,
        artifact_type: str,
        scope_version_id: str,
        decision_at: datetime,
        payload: dict,
    ) -> None:
        payload_hash = stable_json_hash(payload)
        with self._session_factory.begin() as session:
            existing = session.get(RecommendationWorkerArtifactRow, artifact_id)
            if existing is not None:
                if existing.payload_hash != payload_hash or dict(existing.payload_json) != payload:
                    raise ValueError(f"conflicting recommendation artifact: {artifact_id}")
                return
            session.add(
                RecommendationWorkerArtifactRow(
                    artifact_id=artifact_id,
                    orchestration_run_id=orchestration_run_id,
                    worker_name=worker_name,
                    artifact_type=artifact_type,
                    scope_version_id=scope_version_id,
                    decision_at=decision_at,
                    payload_json=payload,
                    payload_hash=payload_hash,
                    created_at=datetime.now(UTC),
                )
            )

    def load(self, artifact_id: str) -> dict | None:
        with self._session_factory() as session:
            row = session.get(RecommendationWorkerArtifactRow, artifact_id)
            return dict(row.payload_json) if row is not None else None


class SQLAlchemyCatalystContextLoader:
    """Load the bounded RAG/prior-thesis view consumed by catalyst research."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def __call__(
        self,
        context_snapshot_ids: list[str] | tuple[str, ...],
    ) -> tuple[CatalystResearchContext, ...]:
        from margin.valuation_discovery.db_models import ResearchContextSnapshotRow

        contexts: list[CatalystResearchContext] = []
        with self._session_factory() as session:
            for context_snapshot_id in context_snapshot_ids:
                row = session.get(ResearchContextSnapshotRow, context_snapshot_id)
                if row is None:
                    raise KeyError(f"research context snapshot not found: {context_snapshot_id}")
                payload = dict(row.payload_json)
                contexts.append(
                    CatalystResearchContext(
                        context_snapshot_id=row.context_snapshot_id,
                        security_id=row.security_id,
                        previous_conclusion=str(
                            payload.get("previous_effective_conclusion") or ""
                        ),
                        previous_assessment_id=(
                            str(payload["previous_effective_assessment_id"])
                            if payload.get("previous_effective_assessment_id")
                            else None
                        ),
                        evidence_ids=tuple(
                            str(value) for value in payload.get("evidence_ids", ()) or ()
                        ),
                        new_filing_document_ids=tuple(
                            str(value)
                            for value in payload.get("new_filing_document_ids", ()) or ()
                        ),
                    )
                )
        return tuple(contexts)

    def load_reporting_contexts(
        self,
        *,
        scope_version_id: str,
        decision_at: datetime,
        seed_context_snapshot_ids: tuple[str, ...],
    ) -> tuple[CatalystResearchContext, ...]:
        """Union current quant seeds with latest in-season filing contexts."""
        from margin.valuation_discovery.db_models import ResearchContextSnapshotRow

        season_start = _reporting_window_start(decision_at)
        with self._session_factory() as session:
            rows = session.scalars(
                select(ResearchContextSnapshotRow)
                .where(
                    ResearchContextSnapshotRow.scope_version_id == scope_version_id,
                    ResearchContextSnapshotRow.decision_at >= season_start,
                    ResearchContextSnapshotRow.decision_at <= decision_at,
                )
                .order_by(
                    ResearchContextSnapshotRow.decision_at.desc(),
                    ResearchContextSnapshotRow.created_at.desc(),
                )
            ).all()
        selected_ids = set(seed_context_snapshot_ids)
        latest_filing_context_by_security: dict[str, str] = {}
        for row in rows:
            payload = dict(row.payload_json)
            if not payload.get("new_filing_document_ids"):
                continue
            latest_filing_context_by_security.setdefault(
                row.security_id,
                row.context_snapshot_id,
            )
        selected_ids.update(latest_filing_context_by_security.values())
        ordered_ids = tuple(
            dict.fromkeys(
                (
                    *seed_context_snapshot_ids,
                    *sorted(selected_ids - set(seed_context_snapshot_ids)),
                )
            )
        )
        return self(ordered_ids)


def _reporting_window_start(decision_at: datetime) -> datetime:
    """Return the start of the reporting season containing ``decision_at``."""
    month = decision_at.month
    start_month = 1 if month <= 4 else 7 if month <= 8 else 10
    return decision_at.replace(month=start_month, day=1, hour=0, minute=0, second=0, microsecond=0)


__all__ = [
    "SQLAlchemyCatalystContextLoader",
    "SQLAlchemyRecommendationArtifactRepository",
]
