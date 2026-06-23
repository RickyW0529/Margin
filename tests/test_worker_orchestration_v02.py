"""DB-backed worker claim, lease recovery, and scheduler-boundary tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete

from margin.core.db_orchestration import (
    OrchestrationRunRow,
    OrchestrationStepAttemptRow,
)
from margin.core.orchestration import DBStepWorker, StepClaim
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
from margin.worker import build_scheduler


def _now() -> datetime:
    """now."""
    return datetime(2026, 6, 22, 12, 0, tzinfo=UTC)


def _repository_with_run() -> MemoryOrchestrationRepository:
    """repository with run."""
    repository = MemoryOrchestrationRepository()
    repository.create_run(
        OrchestrationRun(
            run_id="run-worker-1",
            run_type="valuation_discovery",
            state=RunState.RUNNING,
            scope_version_id="scope-1",
            scope_hash="sha256:" + ("a" * 64),
            trace_id="trace-worker-1",
            created_at=_now(),
            started_at=_now(),
        )
    )
    return repository


def test_worker_claims_pending_step_with_lease() -> None:
    """worker claims pending step with lease."""
    repository = _repository_with_run()
    pending = StepAttempt(
        event_id="step-pending-1",
        run_id="run-worker-1",
        step_id="quant",
        attempt_no=1,
        state_seq=0,
        state=StepState.PENDING,
        input_payload={"scope_version_id": "scope-1"},
        input_ref="scope:scope-1",
        trace_id="trace-worker-1",
        started_at=_now(),
        created_at=_now(),
    )
    repository.append_step_event(pending)
    worker = DBStepWorker(
        repository,
        worker_id="worker-new",
        lease_seconds=60,
    )

    claim = worker.claim_next(now=_now())

    assert isinstance(claim, StepClaim)
    assert claim.lease_owner == "worker-new"
    assert claim.input_ref == "scope:scope-1"
    assert claim.attempt_no == 1
    assert repository.get_latest_step_event(
        "run-worker-1",
        "quant",
    ).state == StepState.RUNNING


def test_worker_retries_expired_running_lease_as_new_attempt() -> None:
    """worker retries expired running lease as new attempt."""
    repository = _repository_with_run()
    expired = StepAttempt(
        event_id="step-expired-1",
        run_id="run-worker-1",
        step_id="news",
        attempt_no=1,
        state_seq=1,
        state=StepState.RUNNING,
        input_hash="sha256:" + ("b" * 64),
        input_ref="quant-result:result-1",
        trace_id="trace-worker-1",
        started_at=_now() - timedelta(minutes=5),
        lease_owner="worker-old",
        lease_expires_at=_now() - timedelta(seconds=1),
        created_at=_now() - timedelta(minutes=5),
    )
    repository.append_step_event(expired)
    worker = DBStepWorker(
        repository,
        worker_id="worker-new",
        lease_seconds=60,
    )

    claim = worker.claim_next(now=_now())

    assert claim is not None
    assert claim.attempt_no == 2
    assert claim.previous_event_id == expired.event_id
    assert claim.input_hash == expired.input_hash
    assert repository.list_step_events("run-worker-1", "news")[0] == expired


def test_worker_does_not_steal_live_lease() -> None:
    """worker does not steal live lease."""
    repository = _repository_with_run()
    live = StepAttempt(
        event_id="step-live-1",
        run_id="run-worker-1",
        step_id="news",
        attempt_no=1,
        state_seq=1,
        state=StepState.RUNNING,
        input_hash="sha256:" + ("b" * 64),
        input_ref="quant-result:result-1",
        trace_id="trace-worker-1",
        started_at=_now(),
        lease_owner="worker-old",
        lease_expires_at=_now() + timedelta(seconds=30),
        created_at=_now(),
    )
    repository.append_step_event(live)

    claim = DBStepWorker(
        repository,
        worker_id="worker-new",
        lease_seconds=60,
    ).claim_next(now=_now())

    assert claim is None


def test_postgres_workers_do_not_claim_same_live_step(database_url: str) -> None:
    """postgres workers do not claim same live step."""
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    run_id = "run-worker-postgres"
    with session_factory.begin() as session:
        session.execute(
            delete(OrchestrationStepAttemptRow).where(
                OrchestrationStepAttemptRow.run_id == run_id
            )
        )
        session.execute(
            delete(OrchestrationRunRow).where(OrchestrationRunRow.run_id == run_id)
        )
    repository = SQLAlchemyOrchestrationRepository(session_factory)
    repository.create_run(
        OrchestrationRun(
            run_id=run_id,
            run_type="valuation_discovery",
            state=RunState.RUNNING,
            scope_version_id="scope-1",
            scope_hash="sha256:" + ("a" * 64),
            trace_id="trace-worker-postgres",
            created_at=_now(),
            started_at=_now(),
        )
    )
    repository.append_step_event(
        StepAttempt(
            event_id="step-postgres-pending",
            run_id=run_id,
            step_id="quant",
            attempt_no=1,
            state_seq=0,
            state=StepState.PENDING,
            input_payload={"scope_version_id": "scope-1"},
            input_ref="scope:scope-1",
            trace_id="trace-worker-postgres",
            started_at=_now(),
            created_at=_now(),
        )
    )

    try:
        first = DBStepWorker(
            repository,
            worker_id="worker-1",
            lease_seconds=60,
        ).claim_next(now=_now())
        second = DBStepWorker(
            repository,
            worker_id="worker-2",
            lease_seconds=60,
        ).claim_next(now=_now())

        assert first is not None
        assert first.lease_owner == "worker-1"
        assert second is None
    finally:
        with session_factory.begin() as session:
            session.execute(
                delete(OrchestrationStepAttemptRow).where(
                    OrchestrationStepAttemptRow.run_id == run_id
                )
            )
            session.execute(
                delete(OrchestrationRunRow).where(
                    OrchestrationRunRow.run_id == run_id
                )
            )
        engine.dispose()


def test_scheduler_registers_orchestration_wakeup_separately() -> None:
    """scheduler registers orchestration wakeup separately."""
    scheduler = build_scheduler(
        interval_seconds=300,
        orchestration_job=lambda: None,
    )

    assert scheduler.get_job("holdings-monitoring") is None
    orchestration_job = scheduler.get_job("orchestration-steps")
    assert orchestration_job is not None
    assert orchestration_job.max_instances == 1
