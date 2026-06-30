"""Contracts for durable v0.2 orchestration run and step state events."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from margin.core.run_states import RunState, StepAttempt, StepState


def _started_at() -> datetime:
    """Return a fixed started-at datetime for test determinism."""
    return datetime(2026, 6, 22, 12, 0, tzinfo=UTC)


def test_step_attempt_is_frozen_and_hashes_input_deterministically() -> None:
    """Test that a step attempt is frozen and hashes input deterministically."""
    first = StepAttempt(
        run_id="run-1",
        step_id="quant",
        attempt_no=1,
        state_seq=0,
        state=StepState.RUNNING,
        input_payload={"scope_version_id": "scope-1", "symbols": ["000001.SZ"]},
        started_at=_started_at(),
        trace_id="trace-1",
    )
    reordered = StepAttempt(
        run_id="run-1",
        step_id="quant",
        attempt_no=1,
        state_seq=0,
        state=StepState.RUNNING,
        input_payload={"symbols": ["000001.SZ"], "scope_version_id": "scope-1"},
        started_at=_started_at(),
        trace_id="trace-1",
    )

    assert first.input_hash.startswith("sha256:")
    assert first.input_hash == reordered.input_hash
    assert "scope_version_id" not in repr(first)

    with pytest.raises(ValidationError):
        first.state = StepState.SUCCEEDED


def test_step_attempt_appends_state_event_without_consuming_retry() -> None:
    """Test that appending a state event does not consume a retry attempt."""
    running = StepAttempt(
        run_id="run-1",
        step_id="news",
        attempt_no=2,
        state_seq=1,
        state=StepState.RUNNING,
        input_payload={"target_batch_id": "batch-1"},
        started_at=_started_at(),
        trace_id="trace-1",
    )

    succeeded = running.append_state(
        StepState.SUCCEEDED,
        output_ref="news-batch-1",
        finished_at=datetime(2026, 6, 22, 12, 1, tzinfo=UTC),
    )

    assert succeeded.attempt_no == 2
    assert succeeded.state_seq == 2
    assert succeeded.previous_event_id == running.event_id
    assert succeeded.input_hash == running.input_hash
    assert running.state == StepState.RUNNING


def test_waiting_states_are_not_terminal() -> None:
    """Test that waiting states are not terminal while succeeded and failed are."""
    assert StepState.WAITING_RATE_LIMIT.is_terminal is False
    assert StepState.WAITING_BUDGET.is_terminal is False
    assert StepState.SUCCEEDED.is_terminal is True
    assert StepState.FAILED_FINAL.is_terminal is True


def test_run_state_values_match_contract() -> None:
    """Test that run state values match the expected contract."""
    assert RunState.FAILED_RETRYABLE.value == "failed_retryable"
    assert RunState.SUCCEEDED_WITH_DEGRADATION.value == "succeeded_with_degradation"
    assert RunState.CANCELLED.is_terminal is True
    assert RunState.RUNNING.is_terminal is False


@pytest.mark.parametrize(
    ("attempt_no", "state_seq"),
    [(0, 0), (1, -1)],
)
def test_step_attempt_rejects_invalid_sequence_numbers(
    attempt_no: int,
    state_seq: int,
) -> None:
    """Test that step attempt rejects invalid sequence numbers.

    Args:
        attempt_no: The attempt number to validate.
        state_seq: The state sequence number to validate.
    """
    with pytest.raises(ValidationError):
        StepAttempt(
            run_id="run-1",
            step_id="quant",
            attempt_no=attempt_no,
            state_seq=state_seq,
            state=StepState.PENDING,
            input_payload={},
            started_at=_started_at(),
            trace_id="trace-1",
        )
