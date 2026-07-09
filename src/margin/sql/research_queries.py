"""Research and AI-graph query factory."""

from __future__ import annotations

from sqlalchemy import Select, select

from margin.research.db_models import (
    AIGraphCheckpointRow,
    LLMCallRecordRow,
    ResearchDeltaOutboxRow,
    ResearchDeltaReviewRow,
    ResearchSnapshotRow,
)


def snapshots_by_run_id(run_id: str) -> Select:
    """Return research snapshots for a run ordered newest-first.

    Args:
        run_id: str: .

    Returns:
        Select: .
    """
    return (
        select(ResearchSnapshotRow)
        .where(ResearchSnapshotRow.run_id == run_id)
        .order_by(
            ResearchSnapshotRow.created_at.desc(),
            ResearchSnapshotRow.snapshot_id.desc(),
        )
    )


def llm_call_by_billing_key(billing_key: str) -> Select:
    """Return an LLM call audit record by its billing key.

    Args:
        billing_key: str: .

    Returns:
        Select: .
    """
    return select(LLMCallRecordRow).where(LLMCallRecordRow.billing_key == billing_key)


def delta_review_by_graph_run(graph_run_id: str) -> Select:
    """Return a delta review row for one graph run.

    Args:
        graph_run_id: str: .

    Returns:
        Select: .
    """
    return select(ResearchDeltaReviewRow).where(ResearchDeltaReviewRow.graph_run_id == graph_run_id)


def delta_outbox_by_graph_run(
    graph_run_id: str,
    event_type: str,
) -> Select:
    """Return a delta outbox row for one graph run and event type.

    Args:
        graph_run_id: str: .
        event_type: str: .

    Returns:
        Select: .
    """
    return select(ResearchDeltaOutboxRow).where(
        ResearchDeltaOutboxRow.graph_run_id == graph_run_id,
        ResearchDeltaOutboxRow.event_type == event_type,
    )


def checkpoint_row(
    thread_id: str,
    checkpoint_ns: str,
    checkpoint_id: str | None = None,
) -> Select:
    """Return a checkpoint row for a thread and namespace.

    Args:
        thread_id: str: .
        checkpoint_ns: str: .
        checkpoint_id: str | None: .

    Returns:
        Select: .
    """
    statement = select(AIGraphCheckpointRow).where(
        AIGraphCheckpointRow.graph_run_id == thread_id,
        AIGraphCheckpointRow.checkpoint_ns == checkpoint_ns,
    )
    if checkpoint_id is not None:
        statement = statement.where(AIGraphCheckpointRow.checkpoint_id == checkpoint_id)
    else:
        statement = statement.order_by(
            AIGraphCheckpointRow.created_at.desc(),
            AIGraphCheckpointRow.checkpoint_id.desc(),
        )
    return statement


def checkpoints_list(
    thread_id: str | None,
    checkpoint_ns: str | None,
    checkpoint_id: str | None,
    before_checkpoint_id: str | None,
) -> Select:
    """Return checkpoints ordered newest-first for listing.

    Args:
        thread_id: str | None: .
        checkpoint_ns: str | None: .
        checkpoint_id: str | None: .
        before_checkpoint_id: str | None: .

    Returns:
        Select: .
    """
    statement = select(AIGraphCheckpointRow).order_by(
        AIGraphCheckpointRow.created_at.desc(),
        AIGraphCheckpointRow.checkpoint_id.desc(),
    )
    if thread_id is not None:
        statement = statement.where(
            AIGraphCheckpointRow.graph_run_id == thread_id,
            AIGraphCheckpointRow.checkpoint_ns == checkpoint_ns,
        )
        if checkpoint_id is not None:
            statement = statement.where(AIGraphCheckpointRow.checkpoint_id == checkpoint_id)
    if before_checkpoint_id is not None:
        statement = statement.where(AIGraphCheckpointRow.checkpoint_id < before_checkpoint_id)
    return statement
