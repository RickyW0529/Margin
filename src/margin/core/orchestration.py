"""DB-backed worker primitives for durable orchestration steps."""

from __future__ import annotations

from datetime import datetime, timedelta

from pydantic import BaseModel, ConfigDict

from margin.core.orchestration_repository import OrchestrationRepository
from margin.core.run_states import StepAttempt


class StepClaim(BaseModel):
    """Lease-bearing claim returned to a step handler."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str
    previous_event_id: str | None
    run_id: str
    step_id: str
    attempt_no: int
    input_hash: str
    input_ref: str | None
    trace_id: str
    lease_owner: str
    lease_expires_at: datetime


class DBStepWorker:
    """Claims one due step atomically and appends a running state event."""

    def __init__(
        self,
        repository: OrchestrationRepository,
        *,
        worker_id: str,
        lease_seconds: int = 300,
        allowed_step_ids: frozenset[str] | None = None,
    ) -> None:
        """Initialize the worker.

        Args:
            repository: The orchestration repository.
            worker_id: Unique identifier for this worker.
            lease_seconds: Lease duration in seconds.
            allowed_step_ids: Optional set of step ids this worker may claim.

        Raises:
            ValueError: If worker_id is empty or lease_seconds is not positive.
        """
        if not worker_id.strip():
            raise ValueError("worker_id is required")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        self._repository = repository
        self._worker_id = worker_id
        self._lease_seconds = lease_seconds
        self._allowed_step_ids = allowed_step_ids

    def claim_next(self, *, now: datetime) -> StepClaim | None:
        """Claim one due step from the repository, if available.

        Args:
            now: Current UTC timestamp.

        Returns:
            A step claim, or None if nothing is due.

        Raises:
            ValueError: If now is not timezone-aware.
        """
        if now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        event = self._repository.claim_next_step(
            worker_id=self._worker_id,
            now=now,
            lease_expires_at=now + timedelta(seconds=self._lease_seconds),
            allowed_step_ids=self._allowed_step_ids,
        )
        return _claim_from_event(event) if event is not None else None


def _claim_from_event(event: StepAttempt) -> StepClaim:
    """Convert a step attempt event into a lease-bearing claim.

    Args:
        event: The step attempt event.

    Returns:
        A StepClaim with lease fields populated.

    Raises:
        ValueError: If the event is missing input_hash or lease fields.
    """
    if event.input_hash is None:
        raise ValueError("claimed step is missing input_hash")
    if event.lease_owner is None or event.lease_expires_at is None:
        raise ValueError("claimed step is missing lease")
    return StepClaim(
        event_id=event.event_id,
        previous_event_id=event.previous_event_id,
        run_id=event.run_id,
        step_id=event.step_id,
        attempt_no=event.attempt_no,
        input_hash=event.input_hash,
        input_ref=event.input_ref,
        trace_id=event.trace_id,
        lease_owner=event.lease_owner,
        lease_expires_at=event.lease_expires_at,
    )
