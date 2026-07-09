"""Persistence tests for durable orchestration runs and append-only step events."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import delete

from margin.core.db_orchestration import (
    OrchestrationRunRow,
    OrchestrationStepAttemptRow,
)
from margin.core.orchestration_repository import (
    MemoryOrchestrationRepository,
    SQLAlchemyOrchestrationRepository,
)
from margin.core.run_states import OrchestrationRun, RunState, StepAttempt, StepState
from margin.storage.base import Base
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)


def _now() -> datetime:
    """Return a fixed datetime for test determinism.

    Returns:
        datetime: .
    """
    return datetime(2026, 6, 22, 12, 0, tzinfo=UTC)


def _run() -> OrchestrationRun:
    """Build a sample orchestration run for repository tests.

    Returns:
        OrchestrationRun: .
    """
    return OrchestrationRun(
        run_id="run-repository-1",
        run_type="valuation_discovery",
        state=RunState.RUNNING,
        scope_version_id="scope-1",
        scope_hash="sha256:" + ("a" * 64),
        idempotency_key_hash="sha256:" + ("b" * 64),
        trace_id="trace-repository-1",
        created_at=_now(),
        started_at=_now(),
    )


def _running_event() -> StepAttempt:
    """Build a sample running step attempt event for repository tests.

    Returns:
        StepAttempt: .
    """
    return StepAttempt(
        event_id="step-event-running",
        run_id="run-repository-1",
        step_id="quant",
        attempt_no=1,
        state_seq=0,
        state=StepState.RUNNING,
        input_payload={"scope_version_id": "scope-1"},
        trace_id="trace-repository-1",
        started_at=_now(),
        created_at=_now(),
    )


def test_memory_repository_derives_latest_event_without_mutating_history() -> None:
    """Test that the memory repository derives latest event without mutating history.

    Returns:
        None: .
    """
    repository = MemoryOrchestrationRepository()
    repository.create_run(_run())
    running = _running_event()
    succeeded = running.append_state(
        StepState.SUCCEEDED,
        output_ref="quant-result-1",
        finished_at=datetime(2026, 6, 22, 12, 1, tzinfo=UTC),
    )

    repository.append_step_event(running)
    repository.append_step_event(succeeded)

    assert repository.get_run("run-repository-1") == _run()
    assert repository.list_step_events("run-repository-1", "quant") == [
        running,
        succeeded,
    ]
    assert repository.get_latest_step_event("run-repository-1", "quant") == succeeded


def test_memory_repository_rejects_duplicate_event_or_sequence() -> None:
    """Test that the memory repository rejects duplicate events or sequences.

    Returns:
        None: .
    """
    repository = MemoryOrchestrationRepository()
    repository.create_run(_run())
    running = _running_event()
    repository.append_step_event(running)

    with pytest.raises(ValueError, match="already exists"):
        repository.append_step_event(running)

    with pytest.raises(ValueError, match="sequence already exists"):
        repository.append_step_event(running.model_copy(update={"event_id": "different-event-id"}))


def test_postgres_repository_round_trips_append_only_step_events(database_url: str) -> None:
    """Test that the PostgreSQL repository round-trips append-only step events.

    Args:
        database_url: str: .

    Returns:
        None: .
    """
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    with session_factory.begin() as session:
        session.execute(
            delete(OrchestrationStepAttemptRow).where(
                OrchestrationStepAttemptRow.run_id == "run-repository-1"
            )
        )
        session.execute(
            delete(OrchestrationRunRow).where(OrchestrationRunRow.run_id == "run-repository-1")
        )

    repository = SQLAlchemyOrchestrationRepository(session_factory)
    running = _running_event()
    succeeded = running.append_state(
        StepState.SUCCEEDED,
        output_ref="quant-result-1",
        finished_at=datetime(2026, 6, 22, 12, 1, tzinfo=UTC),
    )

    try:
        repository.create_run(_run())
        repository.append_step_event(running)
        repository.append_step_event(succeeded)

        reloaded = SQLAlchemyOrchestrationRepository(session_factory)
        assert reloaded.get_run("run-repository-1") == _run()
        persisted_events = reloaded.list_step_events("run-repository-1", "quant")
        assert [event.event_id for event in persisted_events] == [
            running.event_id,
            succeeded.event_id,
        ]
        assert [event.state for event in persisted_events] == [
            StepState.RUNNING,
            StepState.SUCCEEDED,
        ]
        assert [event.input_hash for event in persisted_events] == [
            running.input_hash,
            succeeded.input_hash,
        ]
        assert all(event.input_payload == {} for event in persisted_events)
        assert (
            reloaded.get_latest_step_event("run-repository-1", "quant").event_id
            == succeeded.event_id
        )

        with pytest.raises(ValueError, match="already exists"):
            repository.append_step_event(running)
    finally:
        with session_factory.begin() as session:
            session.execute(
                delete(OrchestrationStepAttemptRow).where(
                    OrchestrationStepAttemptRow.run_id == "run-repository-1"
                )
            )
            session.execute(
                delete(OrchestrationRunRow).where(OrchestrationRunRow.run_id == "run-repository-1")
            )
        engine.dispose()
