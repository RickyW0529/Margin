"""Durable end-to-end valuation-discovery orchestration."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol, TypeVar
from uuid import uuid4

from margin.core.orchestration import DBStepWorker
from margin.core.orchestration_repository import (
    MemoryOrchestrationRepository,
    OrchestrationRepository,
)
from margin.core.run_states import OrchestrationRun, RunState, StepAttempt, StepState


class ValuationDiscoveryStep(StrEnum):
    """Stable ordered step IDs for one valuation-discovery refresh."""

    DATA_FRESHNESS_CHECK = "DATA_FRESHNESS_CHECK"
    DATA_SYNC = "DATA_SYNC"
    SCOPE_RESOLVE = "SCOPE_RESOLVE"
    QUANT_INPUT_BUILD = "QUANT_INPUT_BUILD"
    QUANT_RUN = "QUANT_RUN"
    NEWS_TARGET_SELECTION = "NEWS_TARGET_SELECTION"
    NEWS_REFRESH = "NEWS_REFRESH"
    NEWS_INDEXING = "NEWS_INDEXING"
    RESEARCH_CONTEXT_BUILD = "RESEARCH_CONTEXT_BUILD"
    DASHBOARD_REFRESH = "DASHBOARD_REFRESH"
    AI_DELTA_REVIEW = "AI_DELTA_REVIEW"
    VALUATION_PUBLISH = "VALUATION_PUBLISH"


STEP_ORDER: tuple[ValuationDiscoveryStep, ...] = tuple(ValuationDiscoveryStep)


class RetryableStepError(RuntimeError):
    """A stage is incomplete but can be retried without skipping downstream."""

    def __init__(
        self,
        code: str,
        *,
        retry_after: datetime,
        output_ref: str | None = None,
    ) -> None:
        """Initialize a token-safe retry state."""
        self.code = code
        self.retry_after = retry_after
        self.output_ref = output_ref
        super().__init__(code)


class DataReadinessService(Protocol):
    """Check warehouse freshness and create or poll required sync work."""

    def check(self, **kwargs: Any) -> Any:
        """Return a persisted freshness decision."""

    def ensure_sync(self, **kwargs: Any) -> Any:
        """Return a durable sync decision or run reference."""


class ScopeResolutionService(Protocol):
    """Validate and resolve one frozen research scope."""

    def resolve(self, **kwargs: Any) -> Any:
        """Return a stable scope resolution reference."""


class QuantRefreshService(Protocol):
    """Build quant input and execute one provider-free quant screen."""

    def build_input(self, **kwargs: Any) -> Any:
        """Build and persist a frozen quant input snapshot."""

    def run(self, **kwargs: Any) -> Any:
        """Run quant and return an object with quant_run_id and results."""


class NewsTargetSelectionService(Protocol):
    """Select target companies from deterministic quant results."""

    def select(self, **kwargs: Any) -> Any:
        """Return NewsTarget records."""


class NewsRefreshService(Protocol):
    """Acquire news for a complete target set."""

    def refresh(self, **kwargs: Any) -> Any:
        """Return a durable news refresh reference."""


class IndexingRunner(Protocol):
    """Consume document outbox records into the persistent index."""

    def run_once(self, *, limit: int = ...) -> int:
        """Index one bounded batch."""


class ResearchContextBuilder(Protocol):
    """Build frozen research context snapshots."""

    def build(self, **kwargs: Any) -> Any:
        """Return context snapshot IDs."""


class AIReviewService(Protocol):
    """Execute AI delta reviews from frozen contexts."""

    def review(self, **kwargs: Any) -> Any:
        """Return a review summary."""


class ValuationPublisher(Protocol):
    """Publish effective assessments and refresh dashboard projections."""

    def publish(self, **kwargs: Any) -> Any:
        """Publish effective assessments."""

    def refresh_dashboard(self, **kwargs: Any) -> Any:
        """Refresh or validate the dashboard read projection."""


@dataclass
class ValuationDiscoveryDependencies:
    """Real stage boundaries required by the durable pipeline."""

    repository: ValuationDiscoveryOrchestrationRepository
    data_readiness_service: DataReadinessService | None
    scope_service: ScopeResolutionService | None
    quant_service: QuantRefreshService
    news_target_selector: NewsTargetSelectionService
    news_service: NewsRefreshService
    indexing_runner: IndexingRunner | None = None
    research_context_builder: ResearchContextBuilder | None = None
    ai_review_service: AIReviewService | None = None
    valuation_publisher: ValuationPublisher | None = None


class ValuationDiscoveryOrchestrationRepository:
    """Module-specific adapter over the shared append-only run repository."""

    def __init__(self, inner: OrchestrationRepository) -> None:
        """Initialize the adapter."""
        self._inner = inner

    @classmethod
    def memory(cls) -> ValuationDiscoveryOrchestrationRepository:
        """Return an in-memory adapter for domain tests."""
        return cls(MemoryOrchestrationRepository())

    @property
    def inner(self) -> OrchestrationRepository:
        """Return the shared durable repository."""
        return self._inner

    def create_run(self, run: OrchestrationRun) -> None:
        """Persist one immutable run record."""
        self._inner.create_run(run)

    def get_run(self, run_id: str) -> OrchestrationRun | None:
        """Return one run by ID."""
        return self._inner.get_run(run_id)

    def append_step_event(self, event: StepAttempt) -> None:
        """Append one immutable step-state event."""
        self._inner.append_step_event(event)

    def update_run_state(
        self,
        run_id: str,
        *,
        state: RunState,
        finished_at: datetime | None = None,
    ) -> OrchestrationRun:
        """Update the derived run summary."""
        return self._inner.update_run_state(
            run_id,
            state=state,
            finished_at=finished_at,
        )

    def list_steps(self, run_id: str) -> dict[str, StepAttempt]:
        """Return the latest event for each known step."""
        latest: dict[str, StepAttempt] = {}
        for step in STEP_ORDER:
            event = self._inner.get_latest_step_event(run_id, step.value)
            if event is not None:
                latest[step.value] = event
        return latest


class ValuationDiscoveryOrchestrator:
    """Accept refresh requests by persisting the first pending step only."""

    def __init__(self, dependencies: ValuationDiscoveryDependencies) -> None:
        """Initialize the request-side coordinator."""
        self._dependencies = dependencies

    @property
    def dependencies(self) -> ValuationDiscoveryDependencies:
        """Return the immutable dependency bundle for background workers."""
        return self._dependencies

    def get_run(self, run_id: str) -> OrchestrationRun | None:
        """Return a refresh run."""
        return self._dependencies.repository.get_run(run_id)

    def list_steps(self, run_id: str) -> dict[str, StepAttempt]:
        """Return latest step states for a refresh run."""
        return self._dependencies.repository.list_steps(run_id)

    def list_runs(
        self,
        *,
        scope_version_id: str | None = None,
        state: str | RunState | None = None,
        limit: int = 50,
    ) -> list[OrchestrationRun]:
        """Return recent valuation-discovery runs, newest first."""
        return self._dependencies.repository.inner.list_runs(
            run_type="valuation_discovery",
            scope_version_id=scope_version_id,
            state=state,
            limit=limit,
        )

    def start(
        self,
        *,
        scope_version_id: str,
        decision_at: datetime,
        idempotency_key: str | None = None,
    ) -> OrchestrationRun:
        """Create an idempotent run and enqueue its first step."""
        _validate_aware(decision_at)
        lifecycle_started_at = min(_utc_now(), decision_at)
        run = _new_run(
            scope_version_id=scope_version_id,
            decision_at=decision_at,
            started_at=lifecycle_started_at,
            idempotency_key=idempotency_key,
        )
        try:
            self._dependencies.repository.create_run(run)
        except ValueError:
            existing = self._dependencies.repository.get_run(run.run_id)
            if existing is not None:
                return existing
            raise
        self._dependencies.repository.append_step_event(
            _pending_event(
                run,
                ValuationDiscoveryStep.DATA_FRESHNESS_CHECK,
                lifecycle_started_at,
            )
        )
        return run


class ValuationDiscoveryStepWorker:
    """Lease and execute exactly one durable step per ``run_once`` call."""

    def __init__(
        self,
        dependencies: ValuationDiscoveryDependencies,
        *,
        worker_id: str,
        lease_seconds: int = 300,
    ) -> None:
        """Initialize the step worker."""
        self._dependencies = dependencies
        self._worker = DBStepWorker(
            dependencies.repository.inner,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            allowed_step_ids=frozenset(step.value for step in STEP_ORDER),
        )
        # Durable adapters can reconstruct artifacts from output references. This
        # cache avoids repeated reads while one process handles adjacent steps.
        self._artifacts: dict[str, dict[str, Any]] = {}

    def run_once(self, *, now: datetime) -> bool:
        """Claim and execute one due step."""
        claim = self._worker.claim_next(now=now)
        if claim is None:
            return False
        run = self._dependencies.repository.get_run(claim.run_id)
        if run is None:
            raise RuntimeError(f"orchestration run not found: {claim.run_id}")
        latest = self._dependencies.repository.inner.get_latest_step_event(
            claim.run_id,
            claim.step_id,
        )
        if latest is None or latest.state is not StepState.RUNNING:
            raise RuntimeError("claimed step is not running")
        step = ValuationDiscoveryStep(claim.step_id)
        decision_at = _decision_at_from_run(run)
        try:
            output_ref = self._execute(
                run=run,
                step=step,
                decision_at=decision_at,
            )
        except RetryableStepError as exc:
            self._dependencies.repository.append_step_event(
                latest.append_state(
                    StepState.FAILED_RETRYABLE,
                    output_ref=exc.output_ref,
                    error_code=exc.code,
                    retry_after=exc.retry_after,
                )
            )
            self._dependencies.repository.update_run_state(
                run.run_id,
                state=RunState.FAILED_RETRYABLE,
            )
            return True
        except Exception as exc:
            provider_state = _provider_wait_state(exc, now=now)
            if provider_state is not None:
                state, retry_after = provider_state
                self._dependencies.repository.append_step_event(
                    latest.append_state(
                        state,
                        output_ref=getattr(exc, "output_ref", None),
                        error_code=_error_code(exc),
                        retry_after=retry_after,
                    )
                )
                self._dependencies.repository.update_run_state(
                    run.run_id,
                    state=(
                        RunState.WAITING_BUDGET
                        if state is StepState.WAITING_BUDGET
                        else RunState.WAITING_RATE_LIMIT
                    ),
                )
                return True
            self._dependencies.repository.append_step_event(
                latest.append_state(
                    StepState.FAILED_FINAL,
                    error_code=_error_code(exc),
                    finished_at=now,
                )
            )
            self._skip_downstream(
                run,
                now,
                after=step,
                reason="upstream_failed",
            )
            self._dependencies.repository.update_run_state(
                run.run_id,
                state=RunState.FAILED_FINAL,
                finished_at=now,
            )
            return True

        self._dependencies.repository.append_step_event(
            latest.append_state(
                StepState.SUCCEEDED,
                output_ref=output_ref,
                finished_at=now,
            )
        )
        next_step = _next_step(step)
        if next_step is not None:
            self._dependencies.repository.append_step_event(
                _pending_event(run, next_step, now)
            )
            self._dependencies.repository.update_run_state(
                run.run_id,
                state=RunState.RUNNING,
            )
        else:
            self._dependencies.repository.update_run_state(
                run.run_id,
                state=RunState.SUCCEEDED,
                finished_at=now,
            )
        return True

    def _execute(
        self,
        *,
        run: OrchestrationRun,
        step: ValuationDiscoveryStep,
        decision_at: datetime,
    ) -> str:
        """Dispatch one real stage and return a compact output reference."""
        scope_version_id = run.scope_version_id or ""
        artifacts = self._artifacts.setdefault(run.run_id, {})

        if step is ValuationDiscoveryStep.DATA_FRESHNESS_CHECK:
            service = _require_dependency(
                self._dependencies.data_readiness_service,
                "data readiness service",
            )
            result = service.check(
                scope_version_id=scope_version_id,
                decision_at=decision_at,
            )
            artifacts["freshness"] = result
            return _reference("freshness", result)

        if step is ValuationDiscoveryStep.DATA_SYNC:
            service = _require_dependency(
                self._dependencies.data_readiness_service,
                "data readiness service",
            )
            result = service.ensure_sync(
                orchestration_run_id=run.run_id,
                scope_version_id=scope_version_id,
                decision_at=decision_at,
                freshness=(
                    artifacts.get("freshness")
                    or service.check(
                        scope_version_id=scope_version_id,
                        decision_at=decision_at,
                    )
                ),
            )
            artifacts["data_sync"] = result
            return _reference("data-sync", result)

        if step is ValuationDiscoveryStep.SCOPE_RESOLVE:
            service = _require_dependency(
                self._dependencies.scope_service,
                "scope resolution service",
            )
            result = service.resolve(
                scope_version_id=scope_version_id,
                decision_at=decision_at,
            )
            artifacts["scope"] = result
            return _reference("scope", result)

        if step is ValuationDiscoveryStep.QUANT_INPUT_BUILD:
            result = self._dependencies.quant_service.build_input(
                scope_version_id=scope_version_id,
                decision_at=decision_at,
            )
            artifacts["quant_input"] = result
            return _reference("quant-input", result)

        if step is ValuationDiscoveryStep.QUANT_RUN:
            quant_input = self._quant_input_artifact(run, artifacts)
            result = self._dependencies.quant_service.run(
                scope_version_id=scope_version_id,
                decision_at=decision_at,
                input_snapshot=quant_input,
            )
            artifacts["quant_run"] = result
            return _reference("quant", getattr(result, "quant_run_id", result))

        if step is ValuationDiscoveryStep.NEWS_TARGET_SELECTION:
            quant_run = self._quant_run_artifact(run, artifacts)
            targets = self._select_targets(
                scope_version_id=scope_version_id,
                quant_run=quant_run,
                decision_at=decision_at,
            )
            artifacts["targets"] = targets
            return _reference(
                "targets",
                getattr(quant_run, "quant_run_id", ""),
            )

        if step is ValuationDiscoveryStep.NEWS_REFRESH:
            quant_run = self._quant_run_artifact(run, artifacts)
            result = self._dependencies.news_service.refresh(
                scope_version_id=scope_version_id,
                quant_run_id=str(getattr(quant_run, "quant_run_id", "")),
                decision_at=decision_at,
                targets=self._targets_artifact(
                    run,
                    artifacts,
                    scope_version_id=scope_version_id,
                    quant_run=quant_run,
                    decision_at=decision_at,
                ),
            )
            artifacts["news_refresh"] = result
            return _reference("news", getattr(result, "run_id", result))

        if step is ValuationDiscoveryStep.NEWS_INDEXING:
            runner = _require_dependency(
                self._dependencies.indexing_runner,
                "document indexing runner",
            )
            indexed_count = 0
            for _ in range(100):
                batch_count = runner.run_once(limit=50)
                indexed_count += batch_count
                if batch_count == 0:
                    break
            else:
                raise RetryableStepError(
                    "indexing_backlog_remaining",
                    retry_after=decision_at + timedelta(minutes=1),
                )
            artifacts["indexed_count"] = indexed_count
            return f"indexed:{indexed_count}"

        if step is ValuationDiscoveryStep.RESEARCH_CONTEXT_BUILD:
            builder = _require_dependency(
                self._dependencies.research_context_builder,
                "research context builder",
            )
            quant_run = self._quant_run_artifact(run, artifacts)
            context_ids = tuple(
                builder.build(
                    scope_version_id=scope_version_id,
                    quant_run_id=str(getattr(quant_run, "quant_run_id", "")),
                    news_refresh_run_id=self._news_refresh_run_id(
                        run,
                        artifacts,
                    ),
                    decision_at=decision_at,
                    targets=self._targets_artifact(
                        run,
                        artifacts,
                        scope_version_id=scope_version_id,
                        quant_run=quant_run,
                        decision_at=decision_at,
                    ),
                    results=getattr(quant_run, "results", ()),
                )
            )
            artifacts["context_snapshot_ids"] = context_ids
            return _reference(
                "contexts",
                getattr(quant_run, "quant_run_id", ""),
            )

        if step is ValuationDiscoveryStep.AI_DELTA_REVIEW:
            reviewer = _require_dependency(
                self._dependencies.ai_review_service,
                "AI delta review service",
            )
            result = reviewer.review(
                context_snapshot_ids=self._context_ids_artifact(
                    run,
                    artifacts,
                    scope_version_id=scope_version_id,
                ),
                decision_at=decision_at,
            )
            artifacts["review_summary"] = result
            return _reference("reviews", run.run_id)

        if step is ValuationDiscoveryStep.VALUATION_PUBLISH:
            publisher = _require_dependency(
                self._dependencies.valuation_publisher,
                "valuation publisher",
            )
            quant_run = self._quant_run_artifact(run, artifacts)
            result = publisher.publish(
                scope_version_id=scope_version_id,
                decision_at=decision_at,
                quant_run_id=str(getattr(quant_run, "quant_run_id", "")),
                review_summary=self._review_summary_artifact(
                    run,
                    artifacts,
                    scope_version_id=scope_version_id,
                ),
            )
            artifacts["publish_result"] = result
            return _reference("valuation", result)

        publisher = _require_dependency(
            self._dependencies.valuation_publisher,
            "valuation publisher",
        )
        quant_run = self._quant_run_artifact(run, artifacts)
        return _reference(
            "dashboard",
            publisher.refresh_dashboard(
                scope_version_id=scope_version_id,
                decision_at=decision_at,
                quant_run_id=str(getattr(quant_run, "quant_run_id", "")),
                quant_results=getattr(quant_run, "results", ()),
            ),
        )

    def _quant_input_artifact(
        self,
        run: OrchestrationRun,
        artifacts: dict[str, Any],
    ) -> Any:
        """Return or reload the persisted quant input snapshot."""
        if "quant_input" in artifacts:
            return artifacts["quant_input"]
        snapshot_id = self._prior_output_id(
            run.run_id,
            ValuationDiscoveryStep.QUANT_INPUT_BUILD,
            "quant-input",
        )
        loader = getattr(self._dependencies.quant_service, "load_input", None)
        if not callable(loader):
            raise RuntimeError("quant service does not support input recovery")
        artifacts["quant_input"] = loader(snapshot_id)
        return artifacts["quant_input"]

    def _quant_run_artifact(
        self,
        run: OrchestrationRun,
        artifacts: dict[str, Any],
    ) -> Any:
        """Return or reload a complete quant run and result set."""
        if "quant_run" in artifacts:
            return artifacts["quant_run"]
        quant_run_id = self._prior_output_id(
            run.run_id,
            ValuationDiscoveryStep.QUANT_RUN,
            "quant",
        )
        loader = getattr(self._dependencies.quant_service, "load_run", None)
        if not callable(loader):
            raise RuntimeError("quant service does not support run recovery")
        artifacts["quant_run"] = loader(quant_run_id)
        return artifacts["quant_run"]

    def _news_refresh_run_id(
        self,
        run: OrchestrationRun,
        artifacts: dict[str, Any],
    ) -> str:
        """Return the durable news refresh run identifier."""
        cached = artifacts.get("news_refresh")
        if cached is not None and getattr(cached, "run_id", None):
            return str(cached.run_id)
        return self._prior_output_id(
            run.run_id,
            ValuationDiscoveryStep.NEWS_REFRESH,
            "news",
        )

    def _select_targets(
        self,
        *,
        scope_version_id: str,
        quant_run: Any,
        decision_at: datetime,
    ) -> tuple[Any, ...]:
        """Deterministically reconstruct targets from persisted quant results."""
        return tuple(
            self._dependencies.news_target_selector.select(
                scope_version_id=scope_version_id,
                quant_run_id=str(getattr(quant_run, "quant_run_id", "")),
                results=getattr(quant_run, "results", ()),
                decision_at=decision_at,
            )
        )

    def _targets_artifact(
        self,
        run: OrchestrationRun,
        artifacts: dict[str, Any],
        *,
        scope_version_id: str,
        quant_run: Any,
        decision_at: datetime,
    ) -> tuple[Any, ...]:
        """Return or deterministically rebuild the selected target set."""
        del run
        if "targets" not in artifacts:
            artifacts["targets"] = self._select_targets(
                scope_version_id=scope_version_id,
                quant_run=quant_run,
                decision_at=decision_at,
            )
        return tuple(artifacts["targets"])

    def _context_ids_artifact(
        self,
        run: OrchestrationRun,
        artifacts: dict[str, Any],
        *,
        scope_version_id: str,
    ) -> tuple[str, ...]:
        """Return or reload context IDs created for the persisted quant run."""
        if "context_snapshot_ids" in artifacts:
            return tuple(artifacts["context_snapshot_ids"])
        builder = _require_dependency(
            self._dependencies.research_context_builder,
            "research context builder",
        )
        loader = getattr(builder, "list_context_snapshot_ids", None)
        if not callable(loader):
            raise RuntimeError("research context builder does not support recovery")
        quant_run = self._quant_run_artifact(run, artifacts)
        artifacts["context_snapshot_ids"] = tuple(
            loader(
                scope_version_id=scope_version_id,
                quant_run_id=str(getattr(quant_run, "quant_run_id", "")),
            )
        )
        return tuple(artifacts["context_snapshot_ids"])

    def _review_summary_artifact(
        self,
        run: OrchestrationRun,
        artifacts: dict[str, Any],
        *,
        scope_version_id: str,
    ) -> Any:
        """Return or reload terminal reviews for all frozen contexts."""
        if "review_summary" in artifacts:
            return artifacts["review_summary"]
        reviewer = _require_dependency(
            self._dependencies.ai_review_service,
            "AI delta review service",
        )
        loader = getattr(reviewer, "load_summary", None)
        if not callable(loader):
            raise RuntimeError("AI review service does not support recovery")
        artifacts["review_summary"] = loader(
            context_snapshot_ids=self._context_ids_artifact(
                run,
                artifacts,
                scope_version_id=scope_version_id,
            )
        )
        return artifacts["review_summary"]

    def _prior_output_id(
        self,
        run_id: str,
        step: ValuationDiscoveryStep,
        prefix: str,
    ) -> str:
        """Resolve a required durable entity ID from a succeeded step."""
        event = self._dependencies.repository.inner.get_latest_step_event(
            run_id,
            step.value,
        )
        if (
            event is None
            or event.state is not StepState.SUCCEEDED
            or not event.output_ref
        ):
            raise RuntimeError(f"required step output missing: {step.value}")
        expected = f"{prefix}:"
        if not event.output_ref.startswith(expected):
            raise RuntimeError(f"invalid step output reference: {step.value}")
        identifier = event.output_ref.removeprefix(expected)
        if not identifier:
            raise RuntimeError(f"empty step output reference: {step.value}")
        return identifier

    def _skip_downstream(
        self,
        run: OrchestrationRun,
        now: datetime,
        *,
        after: ValuationDiscoveryStep,
        reason: str,
    ) -> None:
        """Append explicit skipped events for every downstream step."""
        for step in STEP_ORDER[STEP_ORDER.index(after) + 1 :]:
            pending = _pending_event(run, step, now)
            self._dependencies.repository.append_step_event(pending)
            self._dependencies.repository.append_step_event(
                pending.append_state(
                    StepState.SKIPPED,
                    error_code=reason,
                    finished_at=now,
                )
            )


T = TypeVar("T")


def _require_dependency(value: T | None, name: str) -> T:
    """Return a required stage dependency or fail closed."""
    if value is None:
        raise RuntimeError(f"{name} is not configured")
    return value


def _required_artifact(artifacts: dict[str, Any], name: str) -> Any:
    """Return a prior step artifact or fail instead of fabricating output."""
    if name not in artifacts:
        raise RuntimeError(f"required orchestration artifact missing: {name}")
    return artifacts[name]


def _reference(prefix: str, value: Any) -> str:
    """Build a bounded non-secret output reference."""
    for attribute in (
        "version_id",
        "snapshot_id",
        "run_id",
        "quant_run_id",
        "scope_version_id",
    ):
        candidate = getattr(value, attribute, None)
        if candidate:
            return f"{prefix}:{candidate}"[:256]
    if isinstance(value, (str, int, float, bool)):
        return f"{prefix}:{value}"[:256]
    return f"{prefix}:{type(value).__name__}"[:256]


def _next_step(step: ValuationDiscoveryStep) -> ValuationDiscoveryStep | None:
    """Return the next ordered step."""
    index = STEP_ORDER.index(step)
    return STEP_ORDER[index + 1] if index + 1 < len(STEP_ORDER) else None


def _pending_event(
    run: OrchestrationRun,
    step: ValuationDiscoveryStep,
    now: datetime,
) -> StepAttempt:
    """Build the first append-only event for one step."""
    return StepAttempt(
        run_id=run.run_id,
        step_id=step.value,
        attempt_no=1,
        state_seq=0,
        state=StepState.PENDING,
        input_payload={
            "scope_version_id": run.scope_version_id,
            "step": step.value,
        },
        input_ref=f"scope:{run.scope_version_id}",
        trace_id=run.trace_id,
        started_at=now,
        created_at=now,
    )


def _new_run(
    *,
    scope_version_id: str,
    decision_at: datetime,
    started_at: datetime,
    idempotency_key: str | None,
) -> OrchestrationRun:
    """Build a deterministic run when an idempotency key is supplied."""
    key_hash = _hash_optional(idempotency_key)
    run_id = (
        "vdr_"
        + _hash_material(
            scope_version_id,
            decision_at.isoformat(),
            idempotency_key,
        )[:24]
        if idempotency_key is not None
        else f"vdr_{uuid4().hex[:24]}"
    )
    return OrchestrationRun(
        run_id=run_id,
        run_type="valuation_discovery",
        state=RunState.RUNNING,
        scope_version_id=scope_version_id,
        idempotency_key_hash=key_hash,
        trace_id=f"trace_{uuid4().hex[:24]}",
        metadata_json={"decision_at": decision_at.isoformat()},
        created_at=started_at,
        started_at=started_at,
    )


def _decision_at_from_run(run: OrchestrationRun) -> datetime:
    """Return the business PIT timestamp carried by a valuation run."""
    raw_value = run.metadata_json.get("decision_at")
    if isinstance(raw_value, str):
        normalized = raw_value.replace("Z", "+00:00")
        decision_at = datetime.fromisoformat(normalized)
        _validate_aware(decision_at)
        return decision_at
    return run.started_at or run.created_at


def _utc_now() -> datetime:
    """Return the current UTC lifecycle timestamp."""
    return datetime.now(UTC)


def _hash_optional(value: str | None) -> str | None:
    """Hash an optional idempotency key."""
    return None if value is None else "sha256:" + _hash_material(value)


def _hash_material(*parts: str | None) -> str:
    """Hash canonical string material."""
    material = "|".join("" if part is None else part for part in parts)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _error_code(exc: Exception) -> str:
    """Return a bounded, non-secret failure code."""
    explicit = getattr(exc, "code", None)
    if explicit is not None:
        return str(explicit)[:96]
    return exc.__class__.__name__[:96]


def _provider_wait_state(
    exc: Exception,
    *,
    now: datetime,
) -> tuple[StepState, datetime] | None:
    """Map stable Provider errors to explicit wait states."""
    code = str(getattr(exc, "code", ""))
    if code in {"provider_budget_exceeded", "provider_paygo_limit_exceeded"}:
        return StepState.WAITING_BUDGET, now + timedelta(hours=1)
    if code == "provider_429" or bool(getattr(exc, "retryable", False)):
        retry_seconds = int(getattr(exc, "retry_after_seconds", 60) or 60)
        return StepState.WAITING_RATE_LIMIT, now + timedelta(seconds=retry_seconds)
    return None


def _validate_aware(value: datetime) -> None:
    """Require timezone-aware decision timestamps."""
    if value.utcoffset() is None:
        raise ValueError("decision_at must be timezone-aware")
