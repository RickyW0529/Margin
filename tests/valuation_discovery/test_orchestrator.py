"""Valuation discovery orchestrator tests."""

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
    """HTTP-facing start persists work without executing the pipeline inline."""
    dependencies = _dependencies()
    orchestrator = ValuationDiscoveryOrchestrator(dependencies)

    run = orchestrator.start(scope_version_id="scope-1", decision_at=_decision_at())

    steps = dependencies.repository.list_steps(run.run_id)
    assert list(steps) == ["DATA_FRESHNESS_CHECK"]
    assert steps["DATA_FRESHNESS_CHECK"].state == "pending"
    assert dependencies.quant_service.call_count == 0


def test_step_worker_runs_pipeline_in_order() -> None:
    """The durable worker executes and enqueues exactly one next step at a time."""
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
    """Every step can run in a fresh process using durable output references."""
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
    """A missing production stage cannot be reported as succeeded."""
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
    """A pending external sync remains retryable and resumes on a later claim."""
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
    """repeated start with same idempotency key returns same run."""
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
    """service start refresh returns accepted response."""
    service = ValuationDiscoveryService(ValuationDiscoveryOrchestrator(_dependencies()))

    response = service.start_refresh(
        scope_version_id="scope-1",
        decision_at=_decision_at(),
        idempotency_key="k1",
    )

    assert response.http_status == 202
    assert response.status == "accepted"
    assert response.run_id.startswith("vdr_")


def _decision_at() -> datetime:
    """decision at."""
    return datetime(2026, 6, 22, tzinfo=UTC)


def _dependencies() -> ValuationDiscoveryDependencies:
    """dependencies."""
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
    """FakeQuantService."""
    def __init__(self) -> None:
        """Initialize the instance."""
        self._error: str | None = None
        self.call_count = 0
        self._snapshot = "snapshot-1"
        self._run: _FakeQuantRun | None = None

    def fail_with(self, error_code: str) -> None:
        """fail with."""
        self._error = error_code

    def run(self, **_: object) -> _FakeQuantRun:
        """run."""
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
    """FakeQuantRun."""
    quant_run_id: str
    results: tuple[object, ...]


@dataclass(frozen=True)
class _FakeQuantResult:
    """Fake quant result."""

    security_id: str


class _FakeNewsTargetSelector:
    """FakeNewsTargetSelector."""
    def select(self, **_: object) -> tuple[str, ...]:
        """select."""
        return ("000001.SZ",)


class _FakeNewsService:
    """FakeNewsService."""
    def __init__(self) -> None:
        """Initialize the instance."""
        self._error: str | None = None

    def fail_with(self, error_code: str) -> None:
        """fail with."""
        self._error = error_code

    def refresh(self, **_: object) -> str:
        """refresh."""
        if self._error is not None:
            raise RuntimeError(self._error)
        return "news-refresh-1"


class _FakeDataReadinessService:
    """FakeDataReadinessService."""

    def check(self, **_: object) -> str:
        """Return a real readiness decision reference."""
        return "fresh"

    def ensure_sync(self, **_: object) -> str:
        """Return a no-sync-required reference."""
        return "not_required"


class _RetryingDataReadinessService(_FakeDataReadinessService):
    """Data readiness fake that requires one retry."""

    def __init__(self) -> None:
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
    """FakeScopeService."""

    def resolve(self, **_: object) -> str:
        """Resolve a frozen scope."""
        return "scope-1"


class _FakeIndexingRunner:
    """FakeIndexingRunner."""

    def __init__(self) -> None:
        self.calls = 0

    def run_once(self, *, limit: int = 50) -> int:
        """Index one bounded batch."""
        self.calls += 1
        return 1 if limit and self.calls % 2 == 1 else 0


class _FakeContextBuilder:
    """FakeContextBuilder."""

    def __init__(self) -> None:
        self.context_ids: tuple[str, ...] = ()

    def build(self, **_: object) -> tuple[str, ...]:
        """Build frozen contexts."""
        self.context_ids = ("context-1",)
        return self.context_ids

    def list_context_snapshot_ids(self, **_: object) -> tuple[str, ...]:
        """Reload frozen context IDs."""
        return self.context_ids


@dataclass(frozen=True)
class _FakeReviewSummary:
    """Fake review summary."""

    review_ids: tuple[str, ...] = ("review-1",)
    context_snapshot_ids: tuple[str, ...] = ("context-1",)


class _FakeAIReviewService:
    """FakeAIReviewService."""

    def __init__(self) -> None:
        self.summary: _FakeReviewSummary | None = None

    def review(self, **_: object) -> _FakeReviewSummary:
        """Review frozen contexts."""
        self.summary = _FakeReviewSummary()
        return self.summary

    def load_summary(self, **_: object) -> _FakeReviewSummary:
        """Reload terminal reviews."""
        assert self.summary is not None
        return self.summary


class _FakePublisher:
    """FakePublisher."""

    def publish(self, **_: object) -> str:
        """Publish effective assessments."""
        return "assessment-1"

    def refresh_dashboard(self, **_: object) -> str:
        """Refresh dashboard projection."""
        return "dashboard-1"
