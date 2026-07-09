"""v0.2 AI delta review graph state contract tests.

This module verifies that the graph state correctly freezes identity fields
on creation, rejects mutations to identity fields after graph start, allows
immutable updates to non-identity fields, exposes the expected review mode
and outcome enumerations, and that the persistence tables expose the
required audit and idempotency columns.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from margin.research.db_models import (
    AIGraphCheckpointRow,
    AIGraphNodeRunRow,
    AIGraphRunRow,
    LLMCallRecordRow,
    ResearchDeltaOutboxRow,
    ResearchDeltaReviewRow,
    ToolCallRecordRow,
)
from margin.research.graph.state import (
    ReviewMode,
    ReviewOutcome,
    create_initial_state,
)

DECISION_AT = datetime(2026, 6, 22, tzinfo=UTC)


def test_initial_state_freezes_identity_fields() -> None:
    """Verify the initial state freezes identity fields and sets defaults.

    Returns:
        None: .
    """
    state = create_initial_state(
        graph_run_id="graph-1",
        context_snapshot_id="ctx-1",
        context_input_hash="sha256:ctx",
        scope_version_id="scope-1",
        security_id="000001.SZ",
        decision_at=DECISION_AT,
        quant_input_snapshot_id="qin-1",
        current_quant_result_id="qres-1",
        previous_effective_assessment_id="assess-old",
        news_context_bundle_id="news-1",
    )

    assert state.review_mode is None
    assert state.llm_call_count == 0
    assert state.max_llm_calls == 16
    assert state.identity_hash.startswith("sha256:")


def test_identity_fields_cannot_change_after_graph_start() -> None:
    """Verify identity fields cannot be changed after graph start.

    Returns:
        None: .
    """
    state = create_initial_state(
        graph_run_id="graph-1",
        context_snapshot_id="ctx-1",
        context_input_hash="sha256:ctx",
        scope_version_id="scope-1",
        security_id="000001.SZ",
        decision_at=DECISION_AT,
    )

    with pytest.raises(ValueError, match="immutable identity"):
        state.with_updates(security_id="000002.SZ")


def test_non_identity_fields_can_be_updated_immutably() -> None:
    """Verify non-identity fields can be updated immutably without side effects.

    Returns:
        None: .
    """
    state = create_initial_state(
        graph_run_id="graph-1",
        context_snapshot_id="ctx-1",
        context_input_hash="sha256:ctx",
        scope_version_id="scope-1",
        security_id="000001.SZ",
        decision_at=DECISION_AT,
    )

    updated = state.with_updates(
        review_mode=ReviewMode.FULL_REVIEW,
        graph_step_count=1,
    )

    assert state.review_mode is None
    assert updated.review_mode == ReviewMode.FULL_REVIEW
    assert updated.graph_step_count == 1
    assert updated.identity_hash == state.identity_hash


def test_review_outcomes_include_deferred_and_carry_forward() -> None:
    """Verify review modes and outcomes include deferred and carry-forward values.

    Returns:
        None: .
    """
    assert ReviewMode.CARRY_FORWARD_FAST_PATH.value == "carry_forward_fast_path"
    assert ReviewOutcome.REVIEW_DEFERRED.value == "review_deferred"


def test_graph_persistence_tables_expose_audit_and_idempotency_fields() -> None:
    """Verify graph persistence tables expose audit and idempotency fields.

    Returns:
        None: .
    """
    assert {
        AIGraphRunRow.__tablename__,
        AIGraphNodeRunRow.__tablename__,
        AIGraphCheckpointRow.__tablename__,
        ToolCallRecordRow.__tablename__,
        LLMCallRecordRow.__tablename__,
        ResearchDeltaReviewRow.__tablename__,
        ResearchDeltaOutboxRow.__tablename__,
    } == {
        "ai_graph_runs",
        "ai_graph_node_runs",
        "ai_graph_checkpoints",
        "tool_call_records",
        "llm_call_records",
        "research_delta_reviews",
        "research_delta_outbox",
    }
    assert {"identity_hash", "state_hash", "context_input_hash"} <= set(
        AIGraphRunRow.__table__.columns.keys()
    )
    assert {"billing_key", "prompt_hash", "input_tokens", "cost_usd"} <= set(
        LLMCallRecordRow.__table__.columns.keys()
    )
    assert {"policy_version", "request_hash", "result_bytes", "allowed"} <= set(
        ToolCallRecordRow.__table__.columns.keys()
    )
