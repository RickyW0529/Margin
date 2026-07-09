"""Persistent terminal delta-review repository for v0.2 research graph."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from margin.research.db_models import (
    AIGraphRunRow,
    ResearchDeltaOutboxRow,
    ResearchDeltaReviewRow,
)
from margin.research.graph.state import ReviewMode, ReviewOutcome
from margin.sql.research_queries import (
    delta_outbox_by_graph_run,
    delta_review_by_graph_run,
)

RESEARCH_DELTA_PUBLISHED = "research_delta_published"


class ResearchDeltaReview(BaseModel):
    """Immutable terminal delta-review result.."""

    review_id: str
    graph_run_id: str
    context_snapshot_id: str
    security_id: str
    decision_at: datetime
    review_mode: ReviewMode
    outcome: ReviewOutcome
    previous_effective_assessment_id: str | None = None
    effective_assessment_id: str | None = None
    assessment_freshness: str | None = None
    stale_reason: str | None = None
    confidence: float = 0.0
    conclusion: str = ""
    valuation_view: str = "uncertain"
    changed_assumptions: tuple[dict[str, Any], ...] = ()
    evidence_ids: tuple[str, ...] = ()
    model_versions: dict[str, str] = {}
    prompt_versions: dict[str, str] = {}
    tool_versions: dict[str, str] = {}
    llm_call_count: int = 0
    tool_call_count: int = 0
    result_hash: str
    created_at: datetime

    model_config = ConfigDict(frozen=True)


class ResearchDeltaRepository(Protocol):
    """Persistence contract for terminal delta reviews.."""

    def persist_final_review(self, review: ResearchDeltaReview) -> None:
        """Persist a final review and enqueue its publication event.

        Args:
            review: ResearchDeltaReview: .

        Returns:
            None: .
        """

    def get_review(self, review_id: str) -> ResearchDeltaReview | None:
        """Load a review by ID.

        Args:
            review_id: str: .

        Returns:
            ResearchDeltaReview | None: .
        """

    def get_review_by_graph_run(
        self,
        graph_run_id: str,
    ) -> ResearchDeltaReview | None:
        """Load the terminal review for one graph run.

        Args:
            graph_run_id: str: .

        Returns:
            ResearchDeltaReview | None: .
        """

    def count_outbox_events(self, graph_run_id: str, event_type: str) -> int:
        """Count outbox events for one graph run and event type.

        Args:
            graph_run_id: str: .
            event_type: str: .

        Returns:
            int: .
        """


class MemoryResearchDeltaRepository:
    """In-memory implementation used by pure service tests.."""

    def __init__(self) -> None:
        """Initialize an empty repository.

        Returns:
            None: .
        """
        self._reviews: dict[str, ResearchDeltaReview] = {}
        self._review_by_graph_run: dict[str, str] = {}
        self._outbox: dict[tuple[str, str], dict[str, Any]] = {}

    def persist_final_review(self, review: ResearchDeltaReview) -> None:
        """Persist a final review and enqueue its publication event.

        Args:
            review: ResearchDeltaReview: .

        Returns:
            None: .
        """
        existing_id = self._review_by_graph_run.get(review.graph_run_id)
        if existing_id is not None:
            existing = self._reviews[existing_id]
            if existing != review:
                raise ValueError("conflicting final review for graph run")
            self._outbox.setdefault(
                (review.graph_run_id, RESEARCH_DELTA_PUBLISHED),
                _outbox_payload(review),
            )
            return
        if review.review_id in self._reviews and self._reviews[review.review_id] != review:
            raise ValueError("conflicting final review for review id")
        self._reviews[review.review_id] = review
        self._review_by_graph_run[review.graph_run_id] = review.review_id
        self._outbox[(review.graph_run_id, RESEARCH_DELTA_PUBLISHED)] = _outbox_payload(review)

    def get_review(self, review_id: str) -> ResearchDeltaReview | None:
        """Load a review by ID.

        Args:
            review_id: str: .

        Returns:
            ResearchDeltaReview | None: .
        """
        return self._reviews.get(review_id)

    def get_review_by_graph_run(
        self,
        graph_run_id: str,
    ) -> ResearchDeltaReview | None:
        """Load the terminal review for one graph run.

        Args:
            graph_run_id: str: .

        Returns:
            ResearchDeltaReview | None: .
        """
        review_id = self._review_by_graph_run.get(graph_run_id)
        return self._reviews.get(review_id) if review_id is not None else None

    def count_outbox_events(self, graph_run_id: str, event_type: str) -> int:
        """Count outbox events for one graph run and event type.

        Args:
            graph_run_id: str: .
            event_type: str: .

        Returns:
            int: .
        """
        return int((graph_run_id, event_type) in self._outbox)


class SQLAlchemyResearchDeltaRepository:
    """SQLAlchemy-backed final review repository.."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Initialize the repository.

        Args:
            session_factory: Callable[[], Session]: .
            clock: Callable[[], datetime] | None: .

        Returns:
            None: .
        """
        self._session_factory = session_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    def persist_final_review(self, review: ResearchDeltaReview) -> None:
        """Persist final review, terminal run state, and outbox in one transaction.

        Args:
            review: ResearchDeltaReview: .

        Returns:
            None: .
        """
        with self._session_factory.begin() as session:
            graph_run = session.get(AIGraphRunRow, review.graph_run_id)
            if graph_run is None:
                raise ValueError(f"graph run does not exist: {review.graph_run_id}")

            existing = session.scalars(delta_review_by_graph_run(review.graph_run_id)).first()
            if existing is not None:
                if _review_from_row(existing) != review:
                    raise ValueError("conflicting final review for graph run")
                self._ensure_outbox(session, review)
                self._mark_graph_run_completed(session, graph_run, review)
                return

            review_id_conflict = session.get(ResearchDeltaReviewRow, review.review_id)
            if review_id_conflict is not None:
                raise ValueError("conflicting final review for review id")

            session.add(_review_to_row(review))
            self._mark_graph_run_completed(session, graph_run, review)
            self._ensure_outbox(session, review)

    def get_review(self, review_id: str) -> ResearchDeltaReview | None:
        """Load a review by ID.

        Args:
            review_id: str: .

        Returns:
            ResearchDeltaReview | None: .
        """
        with self._session_factory() as session:
            row = session.get(ResearchDeltaReviewRow, review_id)
            return _review_from_row(row) if row is not None else None

    def get_review_by_graph_run(
        self,
        graph_run_id: str,
    ) -> ResearchDeltaReview | None:
        """Load the terminal review for one graph run.

        Args:
            graph_run_id: str: .

        Returns:
            ResearchDeltaReview | None: .
        """
        with self._session_factory() as session:
            row = session.scalars(delta_review_by_graph_run(graph_run_id)).first()
            return _review_from_row(row) if row is not None else None

    def count_outbox_events(self, graph_run_id: str, event_type: str) -> int:
        """Count outbox events for one graph run and event type.

        Args:
            graph_run_id: str: .
            event_type: str: .

        Returns:
            int: .
        """
        with self._session_factory() as session:
            return int(
                session.scalar(
                    select(func.count())
                    .select_from(ResearchDeltaOutboxRow)
                    .where(
                        ResearchDeltaOutboxRow.graph_run_id == graph_run_id,
                        ResearchDeltaOutboxRow.event_type == event_type,
                    )
                )
                or 0
            )

    def _mark_graph_run_completed(
        self,
        session: Session,
        graph_run: AIGraphRunRow,
        review: ResearchDeltaReview,
    ) -> None:
        """Mark the graph run as completed with terminal review metadata.

        Args:
            session: Session: .
            graph_run: AIGraphRunRow: .
            review: ResearchDeltaReview: .

        Returns:
            None: .
        """
        graph_run.status = "completed"
        graph_run.review_mode = review.review_mode.value
        graph_run.outcome = review.outcome.value
        graph_run.effective_assessment_id = review.effective_assessment_id
        graph_run.llm_call_count = review.llm_call_count
        graph_run.tool_call_count = review.tool_call_count
        graph_run.finished_at = self._clock()
        graph_run.updated_at = graph_run.finished_at

    def _ensure_outbox(
        self,
        session: Session,
        review: ResearchDeltaReview,
    ) -> None:
        """Ensure a publication outbox event exists for the review.

        Args:
            session: Session: .
            review: ResearchDeltaReview: .

        Returns:
            None: .
        """
        payload = _outbox_payload(review)
        payload_hash = _hash_json(payload)
        existing = session.scalars(
            delta_outbox_by_graph_run(review.graph_run_id, RESEARCH_DELTA_PUBLISHED)
        ).first()
        if existing is not None:
            if existing.payload_hash != payload_hash or existing.payload != payload:
                raise ValueError("conflicting research delta outbox payload")
            return
        now = self._clock()
        session.add(
            ResearchDeltaOutboxRow(
                outbox_id="rdout_"
                + _hash_json(
                    {
                        "graph_run_id": review.graph_run_id,
                        "event_type": RESEARCH_DELTA_PUBLISHED,
                    }
                ).removeprefix("sha256:")[:24],
                graph_run_id=review.graph_run_id,
                event_type=RESEARCH_DELTA_PUBLISHED,
                payload=payload,
                payload_hash=payload_hash,
                status="pending",
                attempts=0,
                next_attempt_at=now,
                created_at=now,
            )
        )


def _review_to_row(review: ResearchDeltaReview) -> ResearchDeltaReviewRow:
    """Convert a delta review model to a SQLAlchemy row.

    Args:
        review: ResearchDeltaReview: .

    Returns:
        ResearchDeltaReviewRow: .
    """
    return ResearchDeltaReviewRow(
        review_id=review.review_id,
        graph_run_id=review.graph_run_id,
        context_snapshot_id=review.context_snapshot_id,
        security_id=review.security_id,
        decision_at=review.decision_at,
        review_mode=review.review_mode.value,
        outcome=review.outcome.value,
        previous_effective_assessment_id=review.previous_effective_assessment_id,
        effective_assessment_id=review.effective_assessment_id,
        assessment_freshness=review.assessment_freshness,
        stale_reason=review.stale_reason,
        confidence=review.confidence,
        conclusion=review.conclusion,
        valuation_view=review.valuation_view,
        changed_assumptions=list(review.changed_assumptions),
        evidence_ids=list(review.evidence_ids),
        model_versions=dict(review.model_versions),
        prompt_versions=dict(review.prompt_versions),
        tool_versions=dict(review.tool_versions),
        llm_call_count=review.llm_call_count,
        tool_call_count=review.tool_call_count,
        result_hash=review.result_hash,
        created_at=review.created_at,
    )


def _review_from_row(row: ResearchDeltaReviewRow) -> ResearchDeltaReview:
    """Convert a SQLAlchemy row to a delta review model.

    Args:
        row: ResearchDeltaReviewRow: .

    Returns:
        ResearchDeltaReview: .
    """
    return ResearchDeltaReview(
        review_id=row.review_id,
        graph_run_id=row.graph_run_id,
        context_snapshot_id=row.context_snapshot_id,
        security_id=row.security_id,
        decision_at=row.decision_at,
        review_mode=ReviewMode(row.review_mode),
        outcome=ReviewOutcome(row.outcome),
        previous_effective_assessment_id=row.previous_effective_assessment_id,
        effective_assessment_id=row.effective_assessment_id,
        assessment_freshness=row.assessment_freshness,
        stale_reason=row.stale_reason,
        confidence=row.confidence,
        conclusion=row.conclusion,
        valuation_view=row.valuation_view,
        changed_assumptions=tuple(row.changed_assumptions),
        evidence_ids=tuple(row.evidence_ids),
        model_versions=dict(row.model_versions),
        prompt_versions=dict(row.prompt_versions),
        tool_versions=dict(row.tool_versions),
        llm_call_count=row.llm_call_count,
        tool_call_count=row.tool_call_count,
        result_hash=row.result_hash,
        created_at=row.created_at,
    )


def _outbox_payload(review: ResearchDeltaReview) -> dict[str, Any]:
    """Build the publication event payload for a terminal review.

    Args:
        review: ResearchDeltaReview: .

    Returns:
        dict[str, Any]: .
    """
    return {
        "review_id": review.review_id,
        "graph_run_id": review.graph_run_id,
        "context_snapshot_id": review.context_snapshot_id,
        "security_id": review.security_id,
        "decision_at": review.decision_at.isoformat(),
        "outcome": review.outcome.value,
        "effective_assessment_id": review.effective_assessment_id,
        "result_hash": review.result_hash,
    }


def _hash_json(payload: dict[str, Any]) -> str:
    """Return a deterministic SHA-256 hash for a JSON-serializable payload.

    Args:
        payload: dict[str, Any]: .

    Returns:
        str: .
    """
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()
