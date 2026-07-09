"""Repositories for durable runs and append-only step state events."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from threading import RLock
from typing import Protocol

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from margin.core.db_orchestration import (
    OrchestrationRunRow,
    OrchestrationStepAttemptRow,
)
from margin.core.run_states import OrchestrationRun, RunState, StepAttempt, StepState
from margin.sql.core_queries import (
    claim_next_step_statement,
    latest_step_event,
    orchestration_runs,
    step_event_by_sequence,
    step_events_by_run_and_step,
)


class OrchestrationRepository(Protocol):
    """Persistence contract used by run creators and DB-backed workers.."""

    def create_run(self, run: OrchestrationRun) -> None:
        """Persist a new orchestration run.

        Args:
            run: OrchestrationRun: .

        Returns:
            None: .
        """
        ...

    def get_run(self, run_id: str) -> OrchestrationRun | None:
        """Retrieve a run by its identifier.

        Args:
            run_id: str: .

        Returns:
            OrchestrationRun | None: .
        """
        ...

    def list_runs(
        self,
        *,
        run_type: str | None = None,
        scope_version_id: str | None = None,
        state: str | RunState | None = None,
        limit: int = 50,
    ) -> list[OrchestrationRun]:
        """Return persisted runs, newest first, filtered by optional facets.

        Args:
            run_type: str | None: .
            scope_version_id: str | None: .
            state: str | RunState | None: .
            limit: int: .

        Returns:
            list[OrchestrationRun]: .
        """
        ...

    def update_run_state(
        self,
        run_id: str,
        *,
        state: RunState,
        finished_at: datetime | None = None,
    ) -> OrchestrationRun:
        """Update the derived run summary while preserving step-event history.

        Args:
            run_id: str: .
            state: RunState: .
            finished_at: datetime | None: .

        Returns:
            OrchestrationRun: .
        """
        ...

    def append_step_event(self, event: StepAttempt) -> None:
        """Append an immutable step attempt event.

        Args:
            event: StepAttempt: .

        Returns:
            None: .
        """
        ...

    def list_step_events(self, run_id: str, step_id: str) -> list[StepAttempt]:
        """Return all step events for a given run and step, ordered by sequence.

        Args:
            run_id: str: .
            step_id: str: .

        Returns:
            list[StepAttempt]: .
        """
        ...

    def get_latest_step_event(self, run_id: str, step_id: str) -> StepAttempt | None:
        """Return the most recent step event for a given run and step.

        Args:
            run_id: str: .
            step_id: str: .

        Returns:
            StepAttempt | None: .
        """
        ...

    def claim_next_step(
        self,
        *,
        worker_id: str,
        now: datetime,
        lease_expires_at: datetime,
        allowed_step_ids: frozenset[str] | None = None,
    ) -> StepAttempt | None:
        """Atomically claim one due step and return a lease-bearing event.

        Args:
            worker_id: str: .
            now: datetime: .
            lease_expires_at: datetime: .
            allowed_step_ids: frozenset[str] | None: .

        Returns:
            StepAttempt | None: .
        """
        ...


class MemoryOrchestrationRepository:
    """Deterministic process-local repository for domain tests.."""

    def __init__(self) -> None:
        """Initialize an empty in-memory repository.

        Returns:
            None: .
        """
        self._lock = RLock()
        self._runs: dict[str, OrchestrationRun] = {}
        self._events: dict[str, StepAttempt] = {}
        self._sequences: set[tuple[str, str, int, int]] = set()

    def create_run(self, run: OrchestrationRun) -> None:
        """Persist a new orchestration run in memory.

        Args:
            run: OrchestrationRun: .

        Returns:
            None: .
        """
        with self._lock:
            if run.run_id in self._runs:
                raise ValueError(f"orchestration run '{run.run_id}' already exists")
            self._runs[run.run_id] = run

    def get_run(self, run_id: str) -> OrchestrationRun | None:
        """Retrieve a run by its identifier.

        Args:
            run_id: str: .

        Returns:
            OrchestrationRun | None: .
        """
        return self._runs.get(run_id)

    def list_runs(
        self,
        *,
        run_type: str | None = None,
        scope_version_id: str | None = None,
        state: str | RunState | None = None,
        limit: int = 50,
    ) -> list[OrchestrationRun]:
        """Return persisted runs, newest first, filtered by optional facets.

        Args:
            run_type: str | None: .
            scope_version_id: str | None: .
            state: str | RunState | None: .
            limit: int: .

        Returns:
            list[OrchestrationRun]: .
        """
        if limit <= 0:
            return []
        state_value = state.value if isinstance(state, RunState) else state
        runs = [
            run
            for run in self._runs.values()
            if run_type is None or run.run_type == run_type
            if scope_version_id is None or run.scope_version_id == scope_version_id
            if state_value is None or run.state.value == state_value
        ]
        return sorted(runs, key=lambda run: (run.created_at, run.run_id), reverse=True)[:limit]

    def update_run_state(
        self,
        run_id: str,
        *,
        state: RunState,
        finished_at: datetime | None = None,
    ) -> OrchestrationRun:
        """Update the in-memory run summary.

        Args:
            run_id: str: .
            state: RunState: .
            finished_at: datetime | None: .

        Returns:
            OrchestrationRun: .
        """
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                raise KeyError(f"orchestration run '{run_id}' does not exist")
            updated = run.model_copy(
                update={
                    "state": state,
                    "finished_at": finished_at,
                }
            )
            self._runs[run_id] = updated
            return updated

    def append_step_event(self, event: StepAttempt) -> None:
        """Append an immutable step attempt event.

        Args:
            event: StepAttempt: .

        Returns:
            None: .
        """
        with self._lock:
            self._append_step_event_unlocked(event)

    def list_step_events(self, run_id: str, step_id: str) -> list[StepAttempt]:
        """Return all step events for a given run and step, ordered by sequence.

        Args:
            run_id: str: .
            step_id: str: .

        Returns:
            list[StepAttempt]: .
        """
        return sorted(
            (
                event
                for event in self._events.values()
                if event.run_id == run_id and event.step_id == step_id
            ),
            key=lambda event: (event.attempt_no, event.state_seq, event.created_at),
        )

    def get_latest_step_event(self, run_id: str, step_id: str) -> StepAttempt | None:
        """Return the most recent step event for a given run and step.

        Args:
            run_id: str: .
            step_id: str: .

        Returns:
            StepAttempt | None: .
        """
        events = self.list_step_events(run_id, step_id)
        return events[-1] if events else None

    def claim_next_step(
        self,
        *,
        worker_id: str,
        now: datetime,
        lease_expires_at: datetime,
        allowed_step_ids: frozenset[str] | None = None,
    ) -> StepAttempt | None:
        """Atomically claim one due step in memory.

        Args:
            worker_id: str: .
            now: datetime: .
            lease_expires_at: datetime: .
            allowed_step_ids: frozenset[str] | None: .

        Returns:
            StepAttempt | None: .
        """
        with self._lock:
            latest_by_step: dict[tuple[str, str], StepAttempt] = {}
            for event in self._events.values():
                key = (event.run_id, event.step_id)
                current = latest_by_step.get(key)
                if current is None or (event.attempt_no, event.state_seq) > (
                    current.attempt_no,
                    current.state_seq,
                ):
                    latest_by_step[key] = event
            candidates = sorted(
                (
                    event
                    for event in latest_by_step.values()
                    if _is_claimable(event, now)
                    and (allowed_step_ids is None or event.step_id in allowed_step_ids)
                ),
                key=lambda event: (event.created_at, event.run_id, event.step_id),
            )
            if not candidates:
                return None
            claimed = _claimed_event(
                candidates[0],
                worker_id=worker_id,
                now=now,
                lease_expires_at=lease_expires_at,
            )
            self._append_step_event_unlocked(claimed)
            return claimed

    def _append_step_event_unlocked(self, event: StepAttempt) -> None:
        """Append a step event without acquiring the lock.

        Args:
            event: StepAttempt: .

        Returns:
            None: .
        """
        if event.run_id not in self._runs:
            raise ValueError(f"orchestration run '{event.run_id}' does not exist")
        if event.event_id in self._events:
            raise ValueError(f"step event '{event.event_id}' already exists")
        sequence = _event_sequence(event)
        if sequence in self._sequences:
            raise ValueError("step event sequence already exists")
        self._events[event.event_id] = event
        self._sequences.add(sequence)


class SQLAlchemyOrchestrationRepository:
    """PostgreSQL repository preserving immutable step-event history.."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        """Initialize the repository.

        Args:
            session_factory: Callable[[], Session]: .

        Returns:
            None: .
        """
        self._session_factory = session_factory

    def create_run(self, run: OrchestrationRun) -> None:
        """Persist a new orchestration run in PostgreSQL.

        Args:
            run: OrchestrationRun: .

        Returns:
            None: .
        """
        try:
            with self._session_factory.begin() as session:
                session.add(_run_to_row(run))
        except IntegrityError as exc:
            raise ValueError(f"orchestration run '{run.run_id}' already exists") from exc

    def get_run(self, run_id: str) -> OrchestrationRun | None:
        """Retrieve a run by its identifier.

        Args:
            run_id: str: .

        Returns:
            OrchestrationRun | None: .
        """
        with self._session_factory() as session:
            row = session.get(OrchestrationRunRow, run_id)
            return _run_from_row(row) if row is not None else None

    def list_runs(
        self,
        *,
        run_type: str | None = None,
        scope_version_id: str | None = None,
        state: str | RunState | None = None,
        limit: int = 50,
    ) -> list[OrchestrationRun]:
        """Return persisted runs, newest first, filtered by optional facets.

        Args:
            run_type: str | None: .
            scope_version_id: str | None: .
            state: str | RunState | None: .
            limit: int: .

        Returns:
            list[OrchestrationRun]: .
        """
        if limit <= 0:
            return []
        state_value = state.value if isinstance(state, RunState) else state
        statement = orchestration_runs(
            run_type=run_type,
            scope_version_id=scope_version_id,
            state_value=state_value,
            limit=limit,
        )
        with self._session_factory() as session:
            return [_run_from_row(row) for row in session.scalars(statement).all()]

    def update_run_state(
        self,
        run_id: str,
        *,
        state: RunState,
        finished_at: datetime | None = None,
    ) -> OrchestrationRun:
        """Update the materialized run state derived from append-only steps.

        Args:
            run_id: str: .
            state: RunState: .
            finished_at: datetime | None: .

        Returns:
            OrchestrationRun: .
        """
        with self._session_factory.begin() as session:
            row = session.get(OrchestrationRunRow, run_id)
            if row is None:
                raise KeyError(f"orchestration run '{run_id}' does not exist")
            row.state = state.value
            row.finished_at = finished_at
            session.flush()
            return _run_from_row(row)

    def append_step_event(self, event: StepAttempt) -> None:
        """Append an immutable step attempt event.

        Args:
            event: StepAttempt: .

        Returns:
            None: .
        """
        try:
            with self._session_factory.begin() as session:
                existing_id = session.get(OrchestrationStepAttemptRow, event.event_id)
                if existing_id is not None:
                    raise ValueError(f"step event '{event.event_id}' already exists")
                existing_sequence = session.scalar(
                    step_event_by_sequence(
                        event.run_id,
                        event.step_id,
                        event.attempt_no,
                        event.state_seq,
                    )
                )
                if existing_sequence is not None:
                    raise ValueError("step event sequence already exists")
                session.add(_event_to_row(event))
        except IntegrityError as exc:
            raise ValueError("step event already exists or references a missing run") from exc

    def list_step_events(self, run_id: str, step_id: str) -> list[StepAttempt]:
        """Return all step events for a given run and step, ordered by sequence.

        Args:
            run_id: str: .
            step_id: str: .

        Returns:
            list[StepAttempt]: .
        """
        statement = step_events_by_run_and_step(run_id, step_id)
        with self._session_factory() as session:
            return [_event_from_row(row) for row in session.scalars(statement).all()]

    def get_latest_step_event(self, run_id: str, step_id: str) -> StepAttempt | None:
        """Return the most recent step event for a given run and step.

        Args:
            run_id: str: .
            step_id: str: .

        Returns:
            StepAttempt | None: .
        """
        statement = latest_step_event(run_id, step_id)
        with self._session_factory() as session:
            row = session.scalar(statement)
            return _event_from_row(row) if row is not None else None

    def claim_next_step(
        self,
        *,
        worker_id: str,
        now: datetime,
        lease_expires_at: datetime,
        allowed_step_ids: frozenset[str] | None = None,
    ) -> StepAttempt | None:
        """Atomically claim one due step using a PostgreSQL row lock.

        Args:
            worker_id: str: .
            now: datetime: .
            lease_expires_at: datetime: .
            allowed_step_ids: frozenset[str] | None: .

        Returns:
            StepAttempt | None: .
        """
        if allowed_step_ids is not None and not allowed_step_ids:
            return None
        statement = claim_next_step_statement(now, allowed_step_ids)
        with self._session_factory.begin() as session:
            row = session.scalar(statement)
            if row is None:
                return None
            claimed = _claimed_event(
                _event_from_row(row),
                worker_id=worker_id,
                now=now,
                lease_expires_at=lease_expires_at,
            )
            session.add(_event_to_row(claimed))
            session.flush()
            return claimed


def _event_sequence(event: StepAttempt) -> tuple[str, str, int, int]:
    """Return the unique sequence key for a step attempt.

    Args:
        event: StepAttempt: .

    Returns:
        tuple[str, str, int, int]: .
    """
    return (event.run_id, event.step_id, event.attempt_no, event.state_seq)


def _run_to_row(run: OrchestrationRun) -> OrchestrationRunRow:
    """Map a domain OrchestrationRun to its SQLAlchemy row representation.

    Args:
        run: OrchestrationRun: .

    Returns:
        OrchestrationRunRow: .
    """
    return OrchestrationRunRow(
        run_id=run.run_id,
        run_type=run.run_type,
        state=run.state.value,
        scope_version_id=run.scope_version_id,
        scope_hash=run.scope_hash,
        idempotency_key_hash=run.idempotency_key_hash,
        trace_id=run.trace_id,
        metadata_json=run.metadata_json,
        degradation_reasons=list(run.degradation_reasons),
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


def _run_from_row(row: OrchestrationRunRow) -> OrchestrationRun:
    """Map a SQLAlchemy row back to a domain OrchestrationRun.

    Args:
        row: OrchestrationRunRow: .

    Returns:
        OrchestrationRun: .
    """
    return OrchestrationRun(
        run_id=row.run_id,
        run_type=row.run_type,
        state=RunState(row.state),
        scope_version_id=row.scope_version_id,
        scope_hash=row.scope_hash,
        idempotency_key_hash=row.idempotency_key_hash,
        trace_id=row.trace_id,
        metadata_json=dict(row.metadata_json or {}),
        degradation_reasons=tuple(row.degradation_reasons),
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
    )


def _event_to_row(event: StepAttempt) -> OrchestrationStepAttemptRow:
    """Map a domain StepAttempt to its SQLAlchemy row representation.

    Args:
        event: StepAttempt: .

    Returns:
        OrchestrationStepAttemptRow: .
    """
    return OrchestrationStepAttemptRow(
        event_id=event.event_id,
        run_id=event.run_id,
        step_id=event.step_id,
        attempt_no=event.attempt_no,
        state_seq=event.state_seq,
        state=event.state.value,
        input_hash=event.input_hash,
        input_ref=event.input_ref,
        output_ref=event.output_ref,
        error_code=event.error_code,
        retry_after=event.retry_after,
        trace_id=event.trace_id,
        started_at=event.started_at,
        finished_at=event.finished_at,
        lease_owner=event.lease_owner,
        lease_expires_at=event.lease_expires_at,
        previous_event_id=event.previous_event_id,
        created_at=event.created_at,
    )


def _event_from_row(row: OrchestrationStepAttemptRow) -> StepAttempt:
    """Map a SQLAlchemy row back to a domain StepAttempt.

    Args:
        row: OrchestrationStepAttemptRow: .

    Returns:
        StepAttempt: .
    """
    return StepAttempt(
        event_id=row.event_id,
        run_id=row.run_id,
        step_id=row.step_id,
        attempt_no=row.attempt_no,
        state_seq=row.state_seq,
        state=StepState(row.state),
        input_hash=row.input_hash,
        input_ref=row.input_ref,
        output_ref=row.output_ref,
        error_code=row.error_code,
        retry_after=row.retry_after,
        trace_id=row.trace_id,
        started_at=row.started_at,
        finished_at=row.finished_at,
        lease_owner=row.lease_owner,
        lease_expires_at=row.lease_expires_at,
        previous_event_id=row.previous_event_id,
        created_at=row.created_at,
    )


def _is_claimable(event: StepAttempt, now: datetime) -> bool:
    """Determine whether a step attempt is eligible for claiming.

    Args:
        event: StepAttempt: .
        now: datetime: .

    Returns:
        bool: .
    """
    if event.state == StepState.PENDING:
        return True
    if event.state in {
        StepState.FAILED_RETRYABLE,
        StepState.WAITING_RATE_LIMIT,
        StepState.WAITING_BUDGET,
    }:
        return event.retry_after is None or event.retry_after <= now
    return (
        event.state == StepState.RUNNING
        and event.lease_expires_at is not None
        and event.lease_expires_at <= now
    )


def _claimed_event(
    event: StepAttempt,
    *,
    worker_id: str,
    now: datetime,
    lease_expires_at: datetime,
) -> StepAttempt:
    """Create a claimed step attempt event from an eligible candidate.

    Args:
        event: StepAttempt: .
        worker_id: str: .
        now: datetime: .
        lease_expires_at: datetime: .

    Returns:
        StepAttempt: .
    """
    if event.state in {StepState.PENDING, StepState.WAITING_RATE_LIMIT, StepState.WAITING_BUDGET}:
        return event.append_state(
            StepState.RUNNING,
            lease_owner=worker_id,
            lease_expires_at=lease_expires_at,
        )
    return StepAttempt(
        run_id=event.run_id,
        step_id=event.step_id,
        attempt_no=event.attempt_no + 1,
        state_seq=0,
        state=StepState.RUNNING,
        input_hash=event.input_hash,
        input_ref=event.input_ref,
        trace_id=event.trace_id,
        started_at=now,
        lease_owner=worker_id,
        lease_expires_at=lease_expires_at,
        previous_event_id=event.event_id,
        created_at=now,
    )
