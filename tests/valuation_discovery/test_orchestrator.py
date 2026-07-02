"""Valuation discovery orchestrator tests.

This module validates that the orchestrator enqueues steps durably, the
worker runs the pipeline in order, recovery works after worker restart,
missing dependencies fail correctly, retryable steps wait without skipping,
and idempotent starts return the same run.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from margin.valuation_discovery.orchestrator import (
    ValuationDiscoveryDependencies,
    ValuationDiscoveryOrchestrationRepository,
    ValuationDiscoveryOrchestrator,
    ValuationDiscoveryStepWorker,
)
from margin.valuation_discovery.service import ValuationDiscoveryService


def test_start_only_enqueues_first_step() -> None:
    """Verify HTTP-facing start persists work without executing the pipeline inline.

    Returns:
        None.
    """
    dependencies = _dependencies()
    orchestrator = ValuationDiscoveryOrchestrator(dependencies)

    run = orchestrator.start(scope_version_id="scope-1", decision_at=_decision_at())

    steps = dependencies.repository.list_steps(run.run_id)
    assert list(steps) == ["DATA_FRESHNESS_CHECK"]
    assert steps["DATA_FRESHNESS_CHECK"].state == "pending"
    assert dependencies.quant_service.call_count == 0


def test_step_worker_runs_pipeline_in_order() -> None:
    """Verify the durable worker executes and enqueues exactly one next step at a time.

    Returns:
        None.
    """
    dependencies = _dependencies()
    orchestrator = ValuationDiscoveryOrchestrator(dependencies)
    run = orchestrator.start(scope_version_id="scope-1", decision_at=_decision_at())
    worker = ValuationDiscoveryStepWorker(dependencies, worker_id="worker-1")

    processed = 0
    while worker.run_once(now=_decision_at()):
        processed += 1
        assert processed <= 20

    steps = dependencies.repository.list_steps(run.run_id)
    assert processed == 12
    assert all(step.state == "succeeded" for step in steps.values())
    assert dependencies.quant_service.call_count == 1
    assert dependencies.repository.get_run(run.run_id).state == "succeeded"


def test_pipeline_recovers_all_artifacts_after_worker_restart() -> None:
    """Verify every step can run in a fresh process using durable output references.

    Returns:
        None.
    """
    dependencies = _dependencies()
    orchestrator = ValuationDiscoveryOrchestrator(dependencies)
    run = orchestrator.start(
        scope_version_id="scope-1",
        decision_at=_decision_at(),
    )

    processed = 0
    while ValuationDiscoveryStepWorker(
        dependencies,
        worker_id=f"worker-{processed}",
    ).run_once(now=_decision_at()):
        processed += 1
        assert processed <= 20

    assert processed == 12
    assert dependencies.repository.get_run(run.run_id).state == "succeeded"


def test_missing_stage_dependency_fails_instead_of_fake_success() -> None:
    """Verify a missing production stage cannot be reported as succeeded.

    Returns:
        None.
    """
    dependencies = _dependencies()
    dependencies.indexing_runner = None
    orchestrator = ValuationDiscoveryOrchestrator(dependencies)
    run = orchestrator.start(scope_version_id="scope-1", decision_at=_decision_at())
    worker = ValuationDiscoveryStepWorker(dependencies, worker_id="worker-1")

    while worker.run_once(now=_decision_at()):
        pass

    steps = dependencies.repository.list_steps(run.run_id)
    assert steps["NEWS_INDEXING"].state == "failed_final"
    assert steps["RESEARCH_CONTEXT_BUILD"].state == "skipped"
    assert dependencies.repository.get_run(run.run_id).state == "failed_final"


def test_retryable_data_sync_waits_without_skipping_downstream() -> None:
    """Verify a pending external sync remains retryable and resumes on a later claim.

    Returns:
        None.
    """
    dependencies = _dependencies()
    dependencies.data_readiness_service = _RetryingDataReadinessService()
    orchestrator = ValuationDiscoveryOrchestrator(dependencies)
    run = orchestrator.start(scope_version_id="scope-1", decision_at=_decision_at())
    worker = ValuationDiscoveryStepWorker(dependencies, worker_id="worker-1")

    assert worker.run_once(now=_decision_at()) is True
    assert worker.run_once(now=_decision_at()) is True
    steps = dependencies.repository.list_steps(run.run_id)
    assert steps["DATA_SYNC"].state == "failed_retryable"
    assert "SCOPE_RESOLVE" not in steps

    assert worker.run_once(now=_decision_at() + timedelta(minutes=2)) is True
    steps = dependencies.repository.list_steps(run.run_id)
    assert steps["DATA_SYNC"].state == "succeeded"
    assert steps["SCOPE_RESOLVE"].state == "pending"


def test_repeated_start_with_same_idempotency_key_returns_same_run() -> None:
    """Verify repeated start with the same idempotency key returns the same run.

    Returns:
        None.
    """
    dependencies = _dependencies()
    orchestrator = ValuationDiscoveryOrchestrator(dependencies)

    first = orchestrator.start(
        scope_version_id="scope-1",
        decision_at=_decision_at(),
        idempotency_key="k1",
    )
    second = orchestrator.start(
        scope_version_id="scope-1",
        decision_at=_decision_at(),
        idempotency_key="k1",
    )

    assert first.run_id == second.run_id


def test_service_start_refresh_returns_accepted_response() -> None:
    """Verify the service start_refresh returns an accepted 202 response.

    Returns:
        None.
    """
    service = ValuationDiscoveryService(ValuationDiscoveryOrchestrator(_dependencies()))

    response = service.start_refresh(
        scope_version_id="scope-1",
        decision_at=_decision_at(),
        idempotency_key="k1",
    )

    assert response.http_status == 202
    assert response.status == "accepted"
    assert response.run_id.startswith("vdr_")


def test_service_wake_refresh_worker_claims_first_pending_step() -> None:
    """Verify API wake-up claims work without waiting for the polling tick."""
    dependencies = _dependencies()
    service = ValuationDiscoveryService(ValuationDiscoveryOrchestrator(dependencies))
    response = service.start_refresh(
        scope_version_id="scope-1",
        decision_at=_decision_at(),
        idempotency_key="k1",
    )

    processed = service.wake_refresh_worker(max_steps=1, now=_decision_at())

    steps = service.get_refresh_status(response.run_id).steps
    assert processed == 1
    assert steps[0]["step_id"] == "DATA_FRESHNESS_CHECK"
    assert steps[0]["state"] == "succeeded"
    assert steps[1]["step_id"] == "DATA_SYNC"
    assert steps[1]["state"] == "pending"


def test_future_decision_at_does_not_make_step_timestamps_invalid() -> None:
    """Verify business PIT time cannot poison worker lifecycle timestamps."""
    dependencies = _dependencies()
    orchestrator = ValuationDiscoveryOrchestrator(dependencies)
    decision_at = datetime.now(UTC) + timedelta(minutes=10)
    run = orchestrator.start(scope_version_id="scope-1", decision_at=decision_at)
    worker_now = datetime.now(UTC) + timedelta(seconds=1)

    assert ValuationDiscoveryStepWorker(
        dependencies,
        worker_id="worker-1",
    ).run_once(now=worker_now)

    steps = dependencies.repository.list_steps(run.run_id)
    assert steps["DATA_FRESHNESS_CHECK"].state == "succeeded"
    assert dependencies.data_readiness_service.last_check_decision_at == decision_at


def _decision_at() -> datetime:
    """Return the deterministic decision timestamp used across orchestrator tests."""
    return datetime(2026, 6, 22, tzinfo=UTC)


def _dependencies() -> ValuationDiscoveryDependencies:
    """Build deterministic in-memory dependencies with fake services for the orchestrator."""
    return ValuationDiscoveryDependencies(
        repository=ValuationDiscoveryOrchestrationRepository.memory(),
        data_readiness_service=_FakeDataReadinessService(),
        scope_service=_FakeScopeService(),
        quant_service=_FakeQuantService(),
        news_target_selector=_FakeNewsTargetSelector(),
        news_service=_FakeNewsService(),
        indexing_runner=_FakeIndexingRunner(),
        research_context_builder=_FakeContextBuilder(),
        ai_review_service=_FakeAIReviewService(),
        valuation_publisher=_FakePublisher(),
    )


class _FakeQuantService:
    """Fake quant service tracking calls and returning deterministic runs."""

    def __init__(self) -> None:
        """Initialize the fake quant service with no error and zero calls."""
        self._error: str | None = None
        self.call_count = 0
        self._snapshot = "snapshot-1"
        self._run: _FakeQuantRun | None = None

    def fail_with(self, error_code: str) -> None:
        """Configure the service to raise on the next run call."""
        self._error = error_code

    def run(self, **_: object) -> _FakeQuantRun:
        """Run the fake quant pipeline and return a deterministic quant run."""
        self.call_count += 1
        if self._error is not None:
            raise RuntimeError(self._error)
        self._run = _FakeQuantRun(
            quant_run_id="quant-run-1",
            results=(_FakeQuantResult(security_id="000001.SZ"),),
        )
        return self._run

    def build_input(self, **_: object) -> str:
        """Build a frozen quant input reference."""
        return self._snapshot

    def load_input(self, snapshot_id: str) -> str:
        """Reload the frozen input snapshot."""
        assert snapshot_id == self._snapshot
        return self._snapshot

    def load_run(self, quant_run_id: str) -> _FakeQuantRun:
        """Reload the quant run and results."""
        assert self._run is not None
        assert quant_run_id == self._run.quant_run_id
        return self._run


@dataclass(frozen=True)
class _FakeQuantRun:
    """Fake quant run carrying a run ID and result tuple."""
    quant_run_id: str
    results: tuple[object, ...]


@dataclass(frozen=True)
class _FakeQuantResult:
    """Fake quant result carrying only a security ID."""

    security_id: str


class _FakeNewsTargetSelector:
    """Fake news target selector returning a deterministic security tuple."""

    def select(self, **_: object) -> tuple[str, ...]:
        """Return a deterministic tuple of security IDs."""
        return ("000001.SZ",)


class _FakeNewsService:
    """Fake news service that can be configured to fail on refresh."""

    def __init__(self) -> None:
        """Initialize the fake news service with no error."""
        self._error: str | None = None

    def fail_with(self, error_code: str) -> None:
        """Configure the service to raise on the next refresh call."""
        self._error = error_code

    def refresh(self, **_: object) -> str:
        """Run the fake news refresh and return a deterministic refresh ID."""
        if self._error is not None:
            raise RuntimeError(self._error)
        return "news-refresh-1"


class _FakeDataReadinessService:
    """Fake data readiness service returning deterministic readiness decisions."""

    def __init__(self) -> None:
        """Initialize the fake data readiness service with no observed calls."""
        self.last_check_decision_at: datetime | None = None

    def check(self, **kwargs: object) -> str:
        """Return a real readiness decision reference."""
        self.last_check_decision_at = kwargs.get("decision_at")  # type: ignore[assignment]
        return "fresh"

    def ensure_sync(self, **_: object) -> str:
        """Return a no-sync-required reference."""
        return "not_required"


class _RetryingDataReadinessService(_FakeDataReadinessService):
    """Data readiness fake that requires one retry before reporting sync complete."""

    def __init__(self) -> None:
        """Initialize the retrying service with zero calls."""
        self.calls = 0

    def ensure_sync(self, **_: object) -> str:
        """Wait once, then report a completed sync."""
        from margin.valuation_discovery.orchestrator import RetryableStepError

        self.calls += 1
        if self.calls == 1:
            raise RetryableStepError(
                "data_sync_pending",
                retry_after=_decision_at() + timedelta(minutes=1),
            )
        return "sync-completed"


class _FakeScopeService:
    """Fake scope service returning a deterministic frozen scope."""

    def resolve(self, **_: object) -> str:
        """Resolve and return a frozen scope reference."""
        return "scope-1"


class _FakeIndexingRunner:
    """Fake indexing runner that processes one bounded batch at a time."""

    def __init__(self) -> None:
        """Initialize the fake indexing runner with zero calls."""
        self.calls = 0

    def run_once(self, *, limit: int = 50) -> int:
        """Index one bounded batch."""
        self.calls += 1
        return 1 if limit and self.calls % 2 == 1 else 0


class _FakeContextBuilder:
    """Fake context builder returning deterministic frozen context IDs."""

    def __init__(self) -> None:
        """Initialize the fake context builder with no context IDs."""
        self.context_ids: tuple[str, ...] = ()

    def build(self, **_: object) -> tuple[str, ...]:
        """Build and store deterministic frozen context IDs."""
        self.context_ids = ("context-1",)
        return self.context_ids

    def list_context_snapshot_ids(self, **_: object) -> tuple[str, ...]:
        """Reload frozen context IDs."""
        return self.context_ids


@dataclass(frozen=True)
class _FakeReviewSummary:
    """Fake review summary carrying review and context snapshot IDs."""

    review_ids: tuple[str, ...] = ("review-1",)
    context_snapshot_ids: tuple[str, ...] = ("context-1",)


class _FakeAIReviewService:
    """Fake AI review service returning a deterministic review summary."""

    def __init__(self) -> None:
        """Initialize the fake AI review service with no summary."""
        self.summary: _FakeReviewSummary | None = None

    def review(self, **_: object) -> _FakeReviewSummary:
        """Review frozen contexts and return a deterministic summary."""
        self.summary = _FakeReviewSummary()
        return self.summary

    def load_summary(self, **_: object) -> _FakeReviewSummary:
        """Reload terminal reviews."""
        assert self.summary is not None
        return self.summary


class _FakePublisher:
    """Fake publisher returning deterministic assessment and dashboard IDs."""

    def publish(self, **_: object) -> str:
        """Publish and return a deterministic effective assessment ID."""
        return "assessment-1"

    def refresh_dashboard(self, **_: object) -> str:
        """Refresh dashboard projection."""
        return "dashboard-1"
