"""Durable orchestration run and append-only step state contracts."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Self
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _utc_now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(UTC)


def _hash_payload(payload: dict[str, Any]) -> str:
    """Compute a deterministic SHA256 hash for a JSON payload.

    Args:
        payload: The dictionary to hash.

    Returns:
        A string of the form ``sha256:<hex_digest>``.
    """
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    )
    return f"sha256:{hashlib.sha256(serialized.encode('utf-8')).hexdigest()}"


def _validate_aware(value: datetime | None, field_name: str) -> None:
    """Validate that a datetime value is timezone-aware.

    Args:
        value: The datetime to check.
        field_name: Name of the field for error messages.

    Raises:
        ValueError: If the value is not None and lacks timezone info.
    """
    if value is not None and value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


class _StateMixin:
    """Mixin that provides terminal-state detection for StrEnum subclasses."""

    @property
    def is_terminal(self) -> bool:
        """Return True if the state is a terminal (non-retryable) value."""
        return self.value in {
            "succeeded",
            "succeeded_with_degradation",
            "failed_final",
            "skipped",
            "cancelled",
        }


class StepState(_StateMixin, StrEnum):
    """State of one append-only orchestration step event."""

    PENDING = "pending"
    RUNNING = "running"
    WAITING_RATE_LIMIT = "waiting_rate_limit"
    WAITING_BUDGET = "waiting_budget"
    SUCCEEDED = "succeeded"
    SUCCEEDED_WITH_DEGRADATION = "succeeded_with_degradation"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_FINAL = "failed_final"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class RunState(_StateMixin, StrEnum):
    """Current derived state of a durable orchestration run."""

    PENDING = "pending"
    RUNNING = "running"
    WAITING_RATE_LIMIT = "waiting_rate_limit"
    WAITING_BUDGET = "waiting_budget"
    SUCCEEDED = "succeeded"
    SUCCEEDED_WITH_DEGRADATION = "succeeded_with_degradation"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_FINAL = "failed_final"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


_ALLOWED_STEP_TRANSITIONS: dict[StepState, frozenset[StepState]] = {
    StepState.PENDING: frozenset(
        {
            StepState.RUNNING,
            StepState.WAITING_RATE_LIMIT,
            StepState.WAITING_BUDGET,
            StepState.SKIPPED,
            StepState.CANCELLED,
            StepState.FAILED_FINAL,
        }
    ),
    StepState.RUNNING: frozenset(
        {
            StepState.WAITING_RATE_LIMIT,
            StepState.WAITING_BUDGET,
            StepState.SUCCEEDED,
            StepState.SUCCEEDED_WITH_DEGRADATION,
            StepState.FAILED_RETRYABLE,
            StepState.FAILED_FINAL,
            StepState.CANCELLED,
        }
    ),
    StepState.WAITING_RATE_LIMIT: frozenset(
        {
            StepState.RUNNING,
            StepState.FAILED_RETRYABLE,
            StepState.FAILED_FINAL,
            StepState.CANCELLED,
        }
    ),
    StepState.WAITING_BUDGET: frozenset(
        {
            StepState.RUNNING,
            StepState.FAILED_RETRYABLE,
            StepState.FAILED_FINAL,
            StepState.CANCELLED,
        }
    ),
    StepState.FAILED_RETRYABLE: frozenset(
        {
            StepState.RUNNING,
            StepState.FAILED_FINAL,
            StepState.CANCELLED,
        }
    ),
}


class StepAttempt(BaseModel):
    """Immutable state event within one real execution attempt.

    ``attempt_no`` changes only when an execution is retried. ``state_seq``
    changes for append-only lifecycle events within the same attempt.

    Attributes:
        event_id: Unique identifier for the step event.
        run_id: Identifier of the parent orchestration run.
        step_id: Identifier of the orchestration step.
        attempt_no: Execution attempt number (1-based).
        state_seq: Sequence number for state events within the same attempt.
        state: Current state of the step attempt.
        input_payload: Original input payload (excluded from serialization).
        input_hash: SHA-256 hash of the input payload.
        input_ref: Optional reference to the input snapshot.
        output_ref: Optional reference to the output snapshot.
        error_code: Optional error code when the step failed.
        retry_after: Optional timestamp when the step may be retried.
        trace_id: Request trace identifier.
        started_at: UTC timestamp when the attempt started.
        finished_at: UTC timestamp when the attempt finished, if finished.
        lease_owner: Optional identifier of the worker holding the lease.
        lease_expires_at: Optional when the current lease expires.
        previous_event_id: Optional id of the preceding step event.
        created_at: UTC timestamp when the event was created.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str = Field(
        default_factory=lambda: f"step_evt_{uuid4().hex}",
        min_length=1,
        max_length=64,
    )
    run_id: str = Field(min_length=1, max_length=64)
    step_id: str = Field(min_length=1, max_length=96)
    attempt_no: int = Field(ge=1)
    state_seq: int = Field(ge=0)
    state: StepState
    input_payload: dict[str, Any] = Field(default_factory=dict, exclude=True, repr=False)
    input_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    input_ref: str | None = Field(default=None, max_length=256)
    output_ref: str | None = Field(default=None, max_length=256)
    error_code: str | None = Field(default=None, max_length=96)
    retry_after: datetime | None = None
    trace_id: str = Field(min_length=1, max_length=64)
    started_at: datetime
    finished_at: datetime | None = None
    lease_owner: str | None = Field(default=None, max_length=128)
    lease_expires_at: datetime | None = None
    previous_event_id: str | None = Field(default=None, max_length=64)
    created_at: datetime = Field(default_factory=_utc_now)

    @model_validator(mode="after")
    def validate_event(self) -> Self:
        """Validate time/lease invariants and derive the input hash."""
        if self.input_hash is None:
            object.__setattr__(self, "input_hash", _hash_payload(self.input_payload))
        for field_name in (
            "retry_after",
            "started_at",
            "finished_at",
            "lease_expires_at",
            "created_at",
        ):
            _validate_aware(getattr(self, field_name), field_name)
        if (self.lease_owner is None) != (self.lease_expires_at is None):
            raise ValueError("lease_owner and lease_expires_at must be set together")
        if self.finished_at is not None and self.finished_at < self.started_at:
            raise ValueError("finished_at cannot precede started_at")
        if self.state.is_terminal and self.finished_at is None:
            raise ValueError("terminal step state requires finished_at")
        return self

    def append_state(
        self,
        state: StepState,
        *,
        output_ref: str | None = None,
        error_code: str | None = None,
        retry_after: datetime | None = None,
        finished_at: datetime | None = None,
        lease_owner: str | None = None,
        lease_expires_at: datetime | None = None,
    ) -> StepAttempt:
        """Create the next immutable state event for the same attempt.

        Args:
            state: Target step state to transition to.
            output_ref: Optional reference to the output snapshot.
            error_code: Optional error code when transitioning to a failed state.
            retry_after: Optional retry timestamp for retryable failures.
            finished_at: Optional finished timestamp; auto-set for terminal states.
            lease_owner: Optional lease owner for RUNNING transitions.
            lease_expires_at: Optional lease expiry for RUNNING transitions.

        Returns:
            A new immutable StepAttempt with incremented ``state_seq``.

        Raises:
            ValueError: If the transition is not allowed from the current state.
        """
        allowed = _ALLOWED_STEP_TRANSITIONS.get(self.state, frozenset())
        if state not in allowed:
            raise ValueError(f"invalid step transition: {self.state.value} -> {state.value}")
        if state.is_terminal and finished_at is None:
            finished_at = _utc_now()
        return StepAttempt(
            run_id=self.run_id,
            step_id=self.step_id,
            attempt_no=self.attempt_no,
            state_seq=self.state_seq + 1,
            state=state,
            input_hash=self.input_hash,
            input_ref=self.input_ref,
            output_ref=output_ref,
            error_code=error_code,
            retry_after=retry_after,
            trace_id=self.trace_id,
            started_at=self.started_at,
            finished_at=finished_at,
            lease_owner=lease_owner,
            lease_expires_at=lease_expires_at,
            previous_event_id=self.event_id,
        )


class OrchestrationRun(BaseModel):
    """Immutable domain snapshot of a durable orchestration run.

    Attributes:
        run_id: Unique identifier for the run.
        run_type: Type of the run (e.g. ``valuation_discovery``).
        state: Current derived state of the run.
        scope_version_id: Optional frozen scope version identifier.
        scope_hash: Optional hash of the scope configuration.
        idempotency_key_hash: Optional hash of the idempotency key.
        trace_id: Request trace identifier.
        created_at: UTC timestamp when the run was created.
        started_at: UTC timestamp when the run started, if started.
        finished_at: UTC timestamp when the run finished, if finished.
        degradation_reasons: Tuple of degradation reason strings.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str = Field(
        default_factory=lambda: f"run_{uuid4().hex}",
        min_length=1,
        max_length=64,
    )
    run_type: str = Field(min_length=1, max_length=64)
    state: RunState = RunState.PENDING
    scope_version_id: str | None = Field(default=None, max_length=64)
    scope_hash: str | None = Field(default=None, max_length=96)
    idempotency_key_hash: str | None = Field(default=None, max_length=96)
    trace_id: str = Field(min_length=1, max_length=64)
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    degradation_reasons: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_run(self) -> Self:
        """Validate timezone-awareness and temporal invariants."""
        for field_name in ("created_at", "started_at", "finished_at"):
            _validate_aware(getattr(self, field_name), field_name)
        if self.finished_at is not None and self.started_at is None:
            raise ValueError("finished_at requires started_at")
        if (
            self.finished_at is not None
            and self.started_at is not None
            and self.finished_at < self.started_at
        ):
            raise ValueError("finished_at cannot precede started_at")
        if self.state.is_terminal and self.finished_at is None:
            raise ValueError("terminal run state requires finished_at")
        return self
