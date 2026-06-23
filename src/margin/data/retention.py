"""Reference-aware retention for warehouse storage objects."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from margin.data.db_models import (
    CorporateActionRow,
    RawDataSnapshotRow,
    RetentionDeletionAuditRow,
    StandardizedIndicatorFactRow,
)
from margin.news.models import ensure_utc, utc_now


@dataclass(frozen=True)
class RetentionCandidate:
    """Storage object eligible for retention evaluation."""

    object_type: str
    object_id: str
    expires_at: datetime


@dataclass(frozen=True)
class RetentionDeletionResult:
    """Outcome of a retention pass."""

    deleted: tuple[str, ...]
    protected_count: int
    skipped_count: int


class SQLAlchemyRetentionService:
    """Delete only expired and unreferenced warehouse storage objects."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        """Initialize the instance."""
        self._session_factory = session_factory

    def delete_expired(
        self,
        candidates: list[RetentionCandidate],
        *,
        now: datetime | None = None,
    ) -> RetentionDeletionResult:
        """Evaluate retention candidates and append audit rows for every decision."""
        decision_at = ensure_utc(now or utc_now())
        deleted: list[str] = []
        protected_count = 0
        skipped_count = 0
        with self._session_factory.begin() as session:
            for candidate in candidates:
                expires_at = ensure_utc(candidate.expires_at)
                if expires_at > decision_at:
                    skipped_count += 1
                    _audit(
                        session,
                        candidate,
                        decision="skipped",
                        reason="candidate has not expired",
                        reference_count=0,
                        created_at=decision_at,
                    )
                    continue
                if candidate.object_type != "raw_snapshot":
                    skipped_count += 1
                    _audit(
                        session,
                        candidate,
                        decision="skipped",
                        reason=f"unsupported retention object type: {candidate.object_type}",
                        reference_count=0,
                        created_at=decision_at,
                    )
                    continue
                reference_count = _raw_snapshot_reference_count(session, candidate.object_id)
                if reference_count > 0:
                    protected_count += 1
                    _audit(
                        session,
                        candidate,
                        decision="protected",
                        reason="raw snapshot is referenced by warehouse facts",
                        reference_count=reference_count,
                        created_at=decision_at,
                    )
                    continue
                result = session.execute(
                    delete(RawDataSnapshotRow).where(
                        RawDataSnapshotRow.snapshot_id == candidate.object_id
                    )
                )
                if result.rowcount:
                    deleted.append(candidate.object_id)
                    decision = "deleted"
                    reason = "expired raw snapshot had no references"
                else:
                    skipped_count += 1
                    decision = "skipped"
                    reason = "raw snapshot not found"
                _audit(
                    session,
                    candidate,
                    decision=decision,
                    reason=reason,
                    reference_count=0,
                    created_at=decision_at,
                )
        return RetentionDeletionResult(
            deleted=tuple(deleted),
            protected_count=protected_count,
            skipped_count=skipped_count,
        )


def _raw_snapshot_reference_count(session: Session, snapshot_id: str) -> int:
    """raw snapshot reference count."""
    fact_count = session.scalar(
        select(func.count())
        .select_from(StandardizedIndicatorFactRow)
        .where(StandardizedIndicatorFactRow.raw_snapshot_id == snapshot_id)
    )
    corporate_action_count = session.scalar(
        select(func.count())
        .select_from(CorporateActionRow)
        .where(CorporateActionRow.raw_snapshot_id == snapshot_id)
    )
    return int(fact_count or 0) + int(corporate_action_count or 0)


def _audit(
    session: Session,
    candidate: RetentionCandidate,
    *,
    decision: str,
    reason: str,
    reference_count: int,
    created_at: datetime,
) -> None:
    """audit."""
    session.add(
        RetentionDeletionAuditRow(
            audit_id=f"rda_{uuid.uuid4().hex[:12]}",
            object_type=candidate.object_type,
            object_id=candidate.object_id,
            decision=decision,
            reason=reason,
            reference_count=reference_count,
            created_at=created_at,
        )
    )
