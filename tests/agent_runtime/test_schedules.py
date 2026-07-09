"""Tests for persisted agent schedules and scheduled runner behavior."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from margin.agent_runtime.context_store import MemoryAgentContextStore
from margin.agent_runtime.quant_agent import CURRENT_QUANT_AGENT_ML_PROFILE
from margin.agent_runtime.schedules import (
    StockAnalysisSchedule,
    compute_next_run_at,
)
from margin.agents.runtime.scheduled import ScheduledAgentRuntimeRunner
from margin.agents.workers.dashboard_publisher_worker import DashboardPublisherWorker
from margin.config_runtime.bootstrap import SCHEDULED_QUANT_PROFILE_KEY
from margin.config_runtime.models import (
    QuantAgentProfileConfigVersion,
)
from margin.config_runtime.repository import (
    ConfigAdminService,
    ConfigResolver,
    MemoryConfigRepository,
)
from margin.dashboard.models import DashboardFilters, DashboardSort
from margin.dashboard.repository import MemoryDashboardRepository
from margin.research.delta_repository import (
    MemoryResearchDeltaRepository,
    ResearchDeltaReview,
)
from margin.research.graph.state import ReviewMode, ReviewOutcome
from margin.research.llm import DeterministicLLMProvider
from margin.valuation_discovery.adapters import ValuationPublisherAdapter
from margin.valuation_discovery.assessments import EffectiveAssessmentService
from margin.valuation_discovery.models import (
    DataStatus,
    QuantResult,
    ResearchGuardrail,
    ScreeningStatus,
)
from margin.valuation_discovery.orchestrator import (
    ValuationDiscoveryDependencies,
    ValuationDiscoveryOrchestrationRepository,
    ValuationDiscoveryOrchestrator,
)
from margin.valuation_discovery.repository import MemoryValuationDiscoveryRepository
from margin.valuation_discovery.service import ValuationDiscoveryService


def test_compute_next_run_at_rolls_to_next_local_day() -> None:
    """Test daily schedule next-run calculation in local time.

    Returns:
        None: .
    """
    now = datetime(2026, 7, 7, 2, 0, tzinfo=UTC)

    next_run = compute_next_run_at(
        hour=8,
        minute=30,
        timezone="Asia/Shanghai",
        now=now,
    )

    assert next_run == datetime(2026, 7, 8, 0, 30, tzinfo=UTC)


def test_scheduled_runner_triggers_v1_plan_and_refresh() -> None:
    """Test that due schedules trigger v1 planning and valuation refresh.

    Returns:
        None: .
    """
    context_store = MemoryAgentContextStore()
    valuation_service = _FakeValuationService()
    repository = _DueScheduleRepository(
        StockAnalysisSchedule(
            enabled=True,
            hour=8,
            minute=30,
            timezone="Asia/Shanghai",
            scope_version_id="scope-current",
            universe="ALL_A",
            next_run_at=datetime(2026, 7, 7, 0, 30, tzinfo=UTC),
        )
    )

    processed = ScheduledAgentRuntimeRunner(
        repository=repository,
        context_store=context_store,
        valuation_service=valuation_service,
        scope_resolver=lambda scope: "scope-1" if scope == "scope-current" else scope,
        llm_provider_factory=_scheduled_planner_factory,
    ).run_once(now=datetime(2026, 7, 7, 0, 31, tzinfo=UTC))

    assert processed == 1
    assert len(valuation_service.calls) == 1
    scope_version_id, decision_at, idempotency_key, metadata = valuation_service.calls[0]
    assert scope_version_id == "scope-1"
    assert decision_at == datetime(2026, 7, 7, 0, 31, tzinfo=UTC)
    assert idempotency_key == "stock_analysis_daily:2026-07-07"
    assert metadata is not None
    assert metadata["agent_runtime_version"] == "scheduled-agent-runtime-v1"
    assert metadata["agent_run_id"] == "ar_sched_20260707_0830"
    assert metadata["schedule_id"] == "stock_analysis_daily"
    assert metadata["universe"] == "ALL_A"
    assert metadata["global_plan"]["created_by"] == "MainAgent"
    assert metadata["global_plan"]["domain_task_count"] >= 1
    assert metadata["execution_boundary"] == "l3_worker_runtime"
    assert metadata["quant_agent_strategy_profile"]["strategy_family"] == ("ml_lgbm_lifecycle")
    assert metadata["quant_strategy"]["strategy_family"] == "ml_lgbm_lifecycle"
    assert metadata["scheduled_task_intent"] == {
        "planner": "MainAgent",
        "intent_type": "scheduled_stock_analysis",
        "universe": "ALL_A",
        "scope_version_id": "scope-current",
        "language": "zh",
    }
    assert metadata["main_agent_plan"]["planning_mode"] == "prompt_dynamic"
    assert metadata["main_agent_plan"]["planning_prompt_ref"] == "main_agent_scheduled_planner_v1"
    assert metadata["plan_validation"]["valid"] is True
    artifacts = context_store.list_artifacts("ar_sched_20260707_0830")
    assert [artifact.artifact_type for artifact in artifacts] == [
        "scheduled_global_plan",
        "data_readiness",
        "valuation_refresh",
        "l3_execution_report",
    ]
    assert artifacts[0].producer_agent == "MainAgent"
    assert artifacts[2].producer_agent == "QuantExpertAgent"
    assert artifacts[2].payload_json["valuation_refresh_run_id"] == "refresh-1"
    assert artifacts[2].payload_json["dashboard_projection"] == "expected_after_refresh"
    assert artifacts[2].payload_json["worker_layer"] == "L3"
    assert (
        artifacts[2].payload_json["quant_agent_strategy_profile"]["profile_id"]
        == "liquid-large-mid-lgbm-recent-trend80-ddstop-v1"
    )
    assert repository.saved.last_triggered_at == datetime(2026, 7, 7, 0, 31, tzinfo=UTC)


def test_scheduled_runner_records_quant_profile_config_resolution_snapshot() -> None:
    """Scheduled runs persist resolved Quant profile versions, not fixed flows.

    Returns:
        None: .
    """
    decision_at = datetime(2026, 7, 7, 0, 31, tzinfo=UTC)
    config_repository = MemoryConfigRepository()
    config_admin = ConfigAdminService(config_repository)
    config_admin.publish_quant_agent_profile(
        QuantAgentProfileConfigVersion.from_profile(
            version_id="quant-profile-test",
            profile_key=SCHEDULED_QUANT_PROFILE_KEY,
            profile=CURRENT_QUANT_AGENT_ML_PROFILE,
            valid_from=datetime(2026, 1, 1, tzinfo=UTC),
            available_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    config_resolver = ConfigResolver(config_repository)
    context_store = MemoryAgentContextStore()
    valuation_service = _FakeValuationService()
    repository = _DueScheduleRepository(
        StockAnalysisSchedule(
            enabled=True,
            hour=8,
            minute=30,
            timezone="Asia/Shanghai",
            scope_version_id="scope-current",
            universe="ALL_A",
            next_run_at=datetime(2026, 7, 7, 0, 30, tzinfo=UTC),
        )
    )

    ScheduledAgentRuntimeRunner(
        repository=repository,
        context_store=context_store,
        valuation_service=valuation_service,
        scope_resolver=lambda scope: scope,
        llm_provider_factory=_scheduled_planner_factory,
        config_resolver=config_resolver,
    ).run_once(now=decision_at)

    metadata = valuation_service.calls[0][3]
    assert metadata["main_agent_plan"]["planning_prompt_ref"] == "main_agent_scheduled_planner_v1"
    snapshot_id = metadata["config_resolution_snapshot_id"]
    snapshot = config_repository.get_resolution_snapshot(snapshot_id)

    assert [entry.domain for entry in snapshot.entries] == ["quant_agent_profile"]
    assert [entry.version_id for entry in snapshot.entries] == ["quant-profile-test"]


def test_scheduled_runner_can_drive_full_adjusted_dashboard_projection() -> None:
    """Scheduled MainAgent flow reaches StockAnalyst-adjusted dashboard output.

    Returns:
        None: .
    """
    decision_at = datetime(2026, 7, 7, 0, 31, tzinfo=UTC)
    context_store = MemoryAgentContextStore()
    dashboard = MemoryDashboardRepository()
    review_repository = MemoryResearchDeltaRepository()
    valuation_repository = MemoryValuationDiscoveryRepository()
    quant_service = _QuantServiceForFullSchedule()
    dependencies = ValuationDiscoveryDependencies(
        repository=ValuationDiscoveryOrchestrationRepository.memory(),
        data_readiness_service=_ReadyDataService(),
        scope_service=_ScopeService(),
        quant_service=quant_service,
        news_target_selector=_TargetSelector(),
        news_service=_NewsService(),
        indexing_runner=_IndexingRunner(),
        research_context_builder=_ContextBuilder(),
        ai_review_service=_ReviewService(review_repository),
        valuation_publisher=ValuationPublisherAdapter(
            assessment_service=EffectiveAssessmentService(),
            review_repository=review_repository,
            valuation_repository=valuation_repository,
            dashboard_repository=dashboard,
            stock_analyst_agent=DashboardPublisherWorker(
                write_context_artifact=context_store.add_artifact,
                dashboard_repository=dashboard,
            ),
        ),
    )
    valuation_service = ValuationDiscoveryService(ValuationDiscoveryOrchestrator(dependencies))
    repository = _DueScheduleRepository(
        StockAnalysisSchedule(
            enabled=True,
            hour=8,
            minute=30,
            timezone="Asia/Shanghai",
            scope_version_id="scope-current",
            universe="ALL_A",
            next_run_at=datetime(2026, 7, 7, 0, 30, tzinfo=UTC),
        )
    )

    processed = ScheduledAgentRuntimeRunner(
        repository=repository,
        context_store=context_store,
        valuation_service=valuation_service,
        scope_resolver=lambda scope: "scope-1" if scope == "scope-current" else scope,
        llm_provider_factory=_scheduled_planner_factory,
    ).run_once(now=decision_at)
    while valuation_service.create_step_worker(worker_id="schedule-full-flow-test").run_once(
        now=decision_at
    ):
        pass

    response = dashboard.list_research_candidates_v2(
        scope_version_id="scope-1",
        universe_code="ALL_A",
        filters=DashboardFilters(),
        sort=DashboardSort(field="symbol", direction="asc"),
        cursor=None,
        limit=20,
    )

    assert processed == 1
    assert (
        dependencies.repository.inner.list_runs(
            run_type="valuation_discovery",
            scope_version_id="scope-1",
        )[0].state
        == "succeeded"
    )
    assert [item.security_id for item in response.items] == ["000001.SZ", "000002.SZ"]
    assert [item.adjusted_weight for item in response.items] == [0.4, 0.4]
    assert {item.agent_adjustment["source"] for item in response.items} == {
        "DashboardPublisherWorker"
    }
    portfolio_artifact = context_store.get_artifact(
        "ctx_ar_sched_20260707_0830_portfolio_adjustment"
    )
    assert portfolio_artifact is not None
    assert portfolio_artifact.payload_json["removed_security_ids"] == ["000003.SZ"]
    assert context_store.get_artifact("ctx_ar_sched_20260707_0830_dashboard_projection_event")
    assert valuation_repository.list_effective_assessment_pointers()


class _DueScheduleRepository:
    """Fake repository returning one due schedule.."""

    def __init__(self, schedule: StockAnalysisSchedule) -> None:
        """Helper _init__.

        Args:
            schedule: StockAnalysisSchedule: .

        Returns:
            None: .
        """
        self._schedule = schedule
        self.saved = schedule

    def get_stock_analysis_schedule(self) -> StockAnalysisSchedule:
        """Process get_stock_analysis_schedule.

        Returns:
            StockAnalysisSchedule: .
        """
        return self._schedule

    def save_stock_analysis_schedule(
        self,
        schedule: StockAnalysisSchedule,
    ) -> StockAnalysisSchedule:
        """Process save_stock_analysis_schedule.

        Args:
            schedule: StockAnalysisSchedule: .

        Returns:
            StockAnalysisSchedule: .
        """
        self.saved = schedule
        return schedule

    def list_due_stock_analysis_schedules(
        self,
        *,
        now: datetime,
    ) -> list[StockAnalysisSchedule]:
        """Process list_due_stock_analysis_schedules.

        Args:
            now: datetime: .

        Returns:
            list[StockAnalysisSchedule]: .
        """
        return [self._schedule]


class _FakeValuationService:
    """Fake valuation service recording refresh calls.."""

    def __init__(self) -> None:
        """Helper _init__.

        Returns:
            None: .
        """
        self.calls: list[tuple[str, datetime, str | None, dict[str, object] | None]] = []

    def start_refresh(
        self,
        *,
        scope_version_id: str,
        decision_at: datetime,
        idempotency_key: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> object:
        """Process start_refresh.

        Args:
            scope_version_id: str: .
            decision_at: datetime: .
            idempotency_key: str | None: .
            metadata: dict[str, object] | None: .

        Returns:
            object: .
        """
        self.calls.append((scope_version_id, decision_at, idempotency_key, metadata))
        return _FakeRefreshStartResponse(run_id="refresh-1")


class _FakeRefreshStartResponse:
    """Fake refresh response with the attribute used by the schedule runner.."""

    def __init__(self, *, run_id: str) -> None:
        """Helper _init__.

        Args:
            run_id: str: .

        Returns:
            None: .
        """
        self.run_id = run_id


@dataclass(frozen=True)
class _Ref:
    """Small object with common reference attributes for orchestrator tests.."""

    run_id: str | None = None
    version_id: str | None = None
    snapshot_id: str | None = None


class _ReadyDataService:
    """Fake data readiness service that requires no external sync.."""

    def check(self, **_: object) -> _Ref:
        """Process check.

        Args:
            **_: object: .

        Returns:
            _Ref: .
        """
        return _Ref(snapshot_id="freshness-ok")

    def ensure_sync(self, **_: object) -> _Ref:
        """Process ensure_sync.

        Args:
            **_: object: .

        Returns:
            _Ref: .
        """
        return _Ref(run_id="data-sync-ok")


class _ScopeService:
    """Fake scope service returning the frozen scope reference.."""

    def resolve(self, *, scope_version_id: str, **_: object) -> _Ref:
        """Process resolve.

        Args:
            scope_version_id: str: .
            **_: object: .

        Returns:
            _Ref: .
        """
        return _Ref(version_id=scope_version_id)


class _QuantServiceForFullSchedule:
    """Fake provider-free quant service returning ML-style weighted results.."""

    def __init__(self) -> None:
        """Helper _init__.

        Returns:
            None: .
        """
        self._snapshot = _Ref(snapshot_id="qis-schedule")
        self._run = _QuantRunResult(
            quant_run_id="quant-schedule",
            results=(
                _quant_result("000001.SZ", score=90, target_weight=0.5),
                _quant_result("000002.SZ", score=88, target_weight=0.5),
                _quant_result(
                    "000003.SZ",
                    score=86,
                    target_weight=0.2,
                    risk_flags=("short_term_overheat",),
                ),
            ),
        )

    def build_input(self, **_: object) -> _Ref:
        """Process build_input.

        Args:
            **_: object: .

        Returns:
            _Ref: .
        """
        return self._snapshot

    def load_input(self, snapshot_id: str) -> _Ref:
        """Process load_input.

        Args:
            snapshot_id: str: .

        Returns:
            _Ref: .
        """
        assert snapshot_id == self._snapshot.snapshot_id
        return self._snapshot

    def run(self, **_: object) -> _QuantRunResult:
        """Process run.

        Args:
            **_: object: .

        Returns:
            _QuantRunResult: .
        """
        return self._run

    def load_run(self, quant_run_id: str) -> _QuantRunResult:
        """Process load_run.

        Args:
            quant_run_id: str: .

        Returns:
            _QuantRunResult: .
        """
        assert quant_run_id == self._run.quant_run_id
        return self._run


@dataclass(frozen=True)
class _QuantRunResult:
    """Minimal quant result bundle returned by the fake quant service.."""

    quant_run_id: str
    results: tuple[QuantResult, ...]


class _TargetSelector:
    """Fake news target selector returning all quant result securities.."""

    def select(self, *, results: tuple[QuantResult, ...], **_: object) -> tuple[_Ref, ...]:
        """Process select.

        Args:
            results: tuple[QuantResult, ...]: .
            **_: object: .

        Returns:
            tuple[_Ref, ...]: .
        """
        return tuple(_Ref(snapshot_id=result.security_id) for result in results)


class _NewsService:
    """Fake news service representing completed upstream news acquisition.."""

    def refresh(self, **_: object) -> _Ref:
        """Process refresh.

        Args:
            **_: object: .

        Returns:
            _Ref: .
        """
        return _Ref(run_id="news-schedule")


class _IndexingRunner:
    """Fake indexing runner with no backlog.."""

    def run_once(self, *, limit: int = 50) -> int:
        """Process run_once.

        Args:
            limit: int: .

        Returns:
            int: .
        """
        del limit
        return 0


class _ContextBuilder:
    """Fake context builder with durable context recovery support.."""

    def __init__(self) -> None:
        """Helper _init__.

        Returns:
            None: .
        """
        self._ids = ("ctx-schedule-1", "ctx-schedule-2", "ctx-schedule-3")

    def build(self, **_: object) -> tuple[str, ...]:
        """Process build.

        Args:
            **_: object: .

        Returns:
            tuple[str, ...]: .
        """
        return self._ids

    def list_context_snapshot_ids(self, **_: object) -> tuple[str, ...]:
        """Process list_context_snapshot_ids.

        Args:
            **_: object: .

        Returns:
            tuple[str, ...]: .
        """
        return self._ids


class _ReviewService:
    """Fake AI review service that persists one real review for publishing.."""

    def __init__(self, repository: MemoryResearchDeltaRepository) -> None:
        """Helper _init__.

        Args:
            repository: MemoryResearchDeltaRepository: .

        Returns:
            None: .
        """
        self._repository = repository
        self._summary = _ReviewSummary(review_ids=("review-schedule",))

    def review(
        self,
        *,
        context_snapshot_ids: tuple[str, ...],
        **_: object,
    ) -> _ReviewSummary:
        """Process review.

        Args:
            context_snapshot_ids: tuple[str, ...]: .
            **_: object: .

        Returns:
            _ReviewSummary: .
        """
        assert context_snapshot_ids == (
            "ctx-schedule-1",
            "ctx-schedule-2",
            "ctx-schedule-3",
        )
        self._repository.persist_final_review(
            ResearchDeltaReview(
                review_id="review-schedule",
                graph_run_id="graph-schedule",
                context_snapshot_id=context_snapshot_ids[0],
                security_id="000001.SZ",
                decision_at=datetime(2026, 7, 7, 0, 31, tzinfo=UTC),
                review_mode=ReviewMode.DELTA_REVIEW,
                outcome=ReviewOutcome.UPDATE_ASSESSMENT,
                previous_effective_assessment_id=None,
                effective_assessment_id="assessment-schedule",
                assessment_freshness="current",
                stale_reason=None,
                confidence=0.72,
                conclusion="AI review confirmed the quant candidate remains researchable.",
                valuation_view="neutral",
                evidence_ids=("evidence-schedule",),
                result_hash="sha256:schedule-review",
                created_at=datetime(2026, 7, 7, 0, 31, tzinfo=UTC),
            )
        )
        return self._summary

    def load_summary(self, **_: object) -> _ReviewSummary:
        """Process load_summary.

        Args:
            **_: object: .

        Returns:
            _ReviewSummary: .
        """
        return self._summary


@dataclass(frozen=True)
class _ReviewSummary:
    """Minimal review summary consumed by the publisher.."""

    review_ids: tuple[str, ...]


def _scheduled_planner_factory() -> DeterministicLLMProvider:
    """Return the structured MainAgent plan used by scheduled tests."""
    return DeterministicLLMProvider(
        response={
            "steps": [
                {
                    "step_id": "data",
                    "agent": "DataExpertAgent",
                    "task": "Check PIT data readiness for the scheduled research run.",
                    "required_output_types": ["data_readiness"],
                },
                {
                    "step_id": "quant",
                    "agent": "QuantExpertAgent",
                    "task": "Run the quant research line from PIT features.",
                    "required_output_types": ["quant_result"],
                    "depends_on": ["data"],
                },
                {
                    "step_id": "evidence",
                    "agent": "EvidenceRagExpertAgent",
                    "task": "Prepare fundamental evidence coverage for candidates.",
                    "required_output_types": ["evidence_package"],
                    "depends_on": ["data"],
                },
                {
                    "step_id": "stock",
                    "agent": "StockResearchExpertAgent",
                    "task": "Fuse quant, financial-report, sentiment, and risk context.",
                    "required_output_types": ["stock_research_context_capsule"],
                    "depends_on": ["quant", "evidence"],
                },
            ],
            "final_answer_requirements": ["use_approved_capsules_only"],
        }
    )


def _quant_result(
    security_id: str,
    *,
    score: float,
    target_weight: float,
    risk_flags: tuple[str, ...] = (),
) -> QuantResult:
    """Build a deterministic ML-style quant result.

    Args:
        security_id: str: .
        score: float: .
        target_weight: float: .
        risk_flags: tuple[str, ...]: .

    Returns:
        QuantResult: .
    """
    return QuantResult(
        quant_run_id="quant-schedule",
        security_id=security_id,
        final_score=score,
        quality_score=score,
        value_score=score,
        growth_score=score,
        momentum_score=score,
        risk_score=score,
        screening_status=ScreeningStatus.PASS,
        data_status=DataStatus.OK,
        review_required=False,
        review_reasons=(),
        risk_flags=risk_flags,
        research_guardrail=ResearchGuardrail.RESEARCH_ALLOWED,
        reason_summary=f"{security_id} ML score {score}",
        factor_details={
            "strategy_family": "ml_lgbm_lifecycle",
            "ml_strategy": {
                "target_weight": target_weight,
                "risk_controls": {"risk_reasons": list(risk_flags)},
            },
        },
        created_at=datetime(2026, 7, 7, 0, 31, tzinfo=UTC),
    )
