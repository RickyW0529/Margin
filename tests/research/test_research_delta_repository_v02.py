"""v0.2 persistent delta-review repository tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, select

import margin.news.db_models  # noqa: F401 - register FK target tables in Base metadata
from margin.research.db_models import (
    AIGraphCheckpointRow,
    AIGraphRunRow,
    ResearchDeltaOutboxRow,
    ResearchDeltaReviewRow,
)
from margin.research.delta_repository import (
    ResearchDeltaReview,
    SQLAlchemyResearchDeltaRepository,
)
from margin.research.graph.state import ReviewMode, ReviewOutcome
from margin.storage.base import Base
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)

DECISION_AT = datetime(2026, 6, 23, tzinfo=UTC)


def test_finalize_outbox_is_idempotent_and_updates_graph_run(
    database_url: str,
) -> None:
    """final review persistence is transactional and outbox-idempotent."""
    session_factory = _session_factory(database_url)
    graph_run_id = "graph-delta-idempotent"
    _cleanup_graph_rows(session_factory, graph_run_id)
    _seed_graph_run(session_factory, graph_run_id)
    repository = SQLAlchemyResearchDeltaRepository(session_factory)
    review = _review(graph_run_id=graph_run_id)

    repository.persist_final_review(review)
    repository.persist_final_review(review)

    stored = repository.get_review(review.review_id)
    assert stored == review
    assert repository.count_outbox_events(
        graph_run_id,
        "research_delta_published",
    ) == 1
    with session_factory() as session:
        run = session.get(AIGraphRunRow, graph_run_id)
        assert run is not None
        assert run.status == "completed"
        assert run.outcome == ReviewOutcome.UPDATE_ASSESSMENT.value
        assert run.effective_assessment_id == review.effective_assessment_id
        outbox_rows = session.scalars(
            select(ResearchDeltaOutboxRow).where(
                ResearchDeltaOutboxRow.graph_run_id == graph_run_id
            )
        ).all()
        assert len(outbox_rows) == 1
        assert outbox_rows[0].status == "pending"

    _cleanup_graph_rows(session_factory, graph_run_id)


def test_finalize_rejects_conflicting_replay_for_same_graph_run(
    database_url: str,
) -> None:
    """final review persistence rejects conflicting idempotency replays."""
    session_factory = _session_factory(database_url)
    graph_run_id = "graph-delta-conflict"
    _cleanup_graph_rows(session_factory, graph_run_id)
    _seed_graph_run(session_factory, graph_run_id)
    repository = SQLAlchemyResearchDeltaRepository(session_factory)
    review = _review(graph_run_id=graph_run_id)
    conflicting = review.model_copy(
        update={
            "review_id": "review-conflicting",
            "effective_assessment_id": "assess-conflicting",
            "result_hash": "sha256:conflicting",
        }
    )

    repository.persist_final_review(review)

    with pytest.raises(ValueError, match="conflicting final review"):
        repository.persist_final_review(conflicting)

    assert repository.count_outbox_events(
        graph_run_id,
        "research_delta_published",
    ) == 1

    _cleanup_graph_rows(session_factory, graph_run_id)


def _review(*, graph_run_id: str) -> ResearchDeltaReview:
    return ResearchDeltaReview(
        review_id=f"review-{graph_run_id}",
        graph_run_id=graph_run_id,
        context_snapshot_id=f"ctx-{graph_run_id}",
        security_id="000001.SZ",
        decision_at=DECISION_AT,
        review_mode=ReviewMode.DELTA_REVIEW,
        outcome=ReviewOutcome.UPDATE_ASSESSMENT,
        previous_effective_assessment_id="assess-old",
        effective_assessment_id="assess-new",
        assessment_freshness="current",
        stale_reason=None,
        changed_assumptions=({"name": "growth", "status": "updated"},),
        evidence_ids=("ev-1", "ev-2"),
        model_versions={"delta_decision": "deepseek-chat"},
        prompt_versions={"delta_decision": "prompt-v1"},
        tool_versions={"evidence_retrieve": "tool-v1"},
        llm_call_count=2,
        tool_call_count=1,
        result_hash="sha256:result",
        created_at=DECISION_AT,
    )


def _session_factory(database_url: str):
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    return create_session_factory(engine)


def _seed_graph_run(session_factory, graph_run_id: str) -> None:
    now = datetime.now(UTC)
    with session_factory.begin() as session:
        session.add(
            AIGraphRunRow(
                graph_run_id=graph_run_id,
                graph_version="ai-delta-review-v0.2.0",
                context_snapshot_id=f"ctx-{graph_run_id}",
                context_input_hash=f"sha256:ctx-{graph_run_id}",
                identity_hash=f"sha256:identity-{graph_run_id}",
                state_hash="sha256:initial",
                scope_version_id="scope-1",
                security_id="000001.SZ",
                decision_at=DECISION_AT,
                status="running",
                review_mode=ReviewMode.DELTA_REVIEW.value,
                llm_call_count=0,
                tool_call_count=0,
                retrieval_count=0,
                repair_count=0,
                created_at=now,
                updated_at=now,
                started_at=now,
            )
        )


def _cleanup_graph_rows(session_factory, graph_run_id: str) -> None:
    with session_factory.begin() as session:
        for row in (
            ResearchDeltaOutboxRow,
            ResearchDeltaReviewRow,
            AIGraphCheckpointRow,
            AIGraphRunRow,
        ):
            session.execute(delete(row).where(row.graph_run_id == graph_run_id))
