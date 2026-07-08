"""Agent runtime API routes for Q&A and scheduled stock analysis."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from margin.agent_runtime.expert_agents import DataAnalystAgent, GeneralQnaAgent
from margin.agent_runtime.main_agent import MainAgentPlanningError, MainAgentRuntime
from margin.agent_runtime.models import AgentExecutionStatus, AgentStep, ContextArtifact
from margin.agent_runtime.schedules import (
    AgentScheduleRepository,
    StockAnalysisSchedule,
)
from margin.api.dependencies import (
    get_agent_schedule_repository,
    get_dashboard_services,
    get_llm_provider_factory,
    get_main_agent_runtime,
    get_strategy_service,
    require_local_admin,
)
from margin.dashboard.service import DashboardServiceBundle
from margin.research.llm import LLMProvider
from margin.strategy.service import StrategyService

router = APIRouter(prefix="/api/v1", tags=["agent-runtime"])

RuntimeDep = Annotated[MainAgentRuntime, Depends(get_main_agent_runtime)]
DashboardServices = Annotated[DashboardServiceBundle, Depends(get_dashboard_services)]
StrategyServices = Annotated[StrategyService, Depends(get_strategy_service)]
LLMProviderFactory = Annotated[
    Callable[[], LLMProvider],
    Depends(get_llm_provider_factory),
]
ScheduleRepo = Annotated[
    AgentScheduleRepository,
    Depends(get_agent_schedule_repository),
]


class UserQnaRunRequest(BaseModel):
    """User Q&A request routed through MainAgent."""

    model_config = ConfigDict(extra="forbid")

    scope_version_id: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=2000)
    universe: str = Field(default="ALL_A", min_length=1, max_length=32)
    language: str = Field(default="zh", pattern="^(zh|en)$")


class GuardrailSummaryResponse(BaseModel):
    """Safe guardrail summary returned to the frontend."""

    allowed: bool
    decision: str
    summary: str
    triggered_policies: list[str] = Field(default_factory=list)


class AgentTraceStepResponse(BaseModel):
    """One user-visible expert-agent trace row."""

    step_id: str
    expert_agent_name: str
    skill_id: str
    status: str


class AgentTraceResponse(BaseModel):
    """User-visible MainAgent trace."""

    steps: list[AgentTraceStepResponse]


class ContextArtifactSummaryResponse(BaseModel):
    """Short Context Store artifact summary safe for the frontend."""

    artifact_id: str
    artifact_type: str
    producer_agent: str
    payload_hash: str


class UserQnaRunResponse(BaseModel):
    """Response returned by the MainAgent-backed Q&A endpoint."""

    run_id: str
    answer: str
    guardrail: GuardrailSummaryResponse
    agent_trace: AgentTraceResponse
    artifacts: list[ContextArtifactSummaryResponse]
    references: list[dict[str, str]]


class StockAnalysisScheduleUpdate(BaseModel):
    """Request body for updating the daily stock-analysis schedule."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    hour: int = Field(ge=0, le=23)
    minute: int = Field(ge=0, le=59)
    timezone: str = "Asia/Shanghai"
    scope_version_id: str = Field(default="scope-current", min_length=1, max_length=64)
    universe: str = Field(default="ALL_A", min_length=1, max_length=32)


class StockAnalysisScheduleResponse(BaseModel):
    """Persisted stock-analysis schedule returned to the frontend."""

    schedule_id: str
    run_type: str
    enabled: bool
    hour: int
    minute: int
    timezone: str
    scope_version_id: str
    universe: str
    last_triggered_at: datetime | None
    next_run_at: datetime | None
    updated_at: datetime


@dataclass(frozen=True)
class _UserQnaExecution:
    answer: str
    step_statuses: dict[str, AgentExecutionStatus]
    artifacts: tuple[ContextArtifact, ...]
    references: tuple[dict[str, str], ...]


@router.post("/agent-runs/user-qna", response_model=UserQnaRunResponse)
def run_user_qna_agent(
    request: UserQnaRunRequest,
    runtime: RuntimeDep,
    services: DashboardServices,
    strategy_service: StrategyServices,
    llm_provider_factory: LLMProviderFactory,
) -> UserQnaRunResponse:
    """Run a read-only user Q&A request through MainAgent-planned ExpertAgents."""
    run_id = f"ar_qna_{uuid4().hex}"
    try:
        plan_result = runtime.create_user_qna_plan(
            run_id=run_id,
            user_input=request.message,
        )
    except MainAgentPlanningError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "main_agent_planner_unavailable",
                "message": str(exc),
            },
        ) from exc
    guardrail = plan_result.guardrail_decision
    if not guardrail.allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "agent_guardrail_blocked",
                "message": guardrail.user_message or guardrail.evaluation_summary,
                "triggered_policies": list(guardrail.triggered_policies),
            },
        )

    execution = _execute_user_qna_plan(
        request=request,
        run_id=run_id,
        plan_steps=plan_result.plan.steps,
        runtime=runtime,
        services=services,
        strategy_service=strategy_service,
        llm_provider_factory=llm_provider_factory,
    )

    return UserQnaRunResponse(
        run_id=run_id,
        answer=execution.answer,
        guardrail=GuardrailSummaryResponse(
            allowed=guardrail.allowed,
            decision=guardrail.decision,
            summary=guardrail.safe_summary or guardrail.evaluation_summary,
            triggered_policies=list(guardrail.triggered_policies),
        ),
        agent_trace=AgentTraceResponse(
            steps=[
                AgentTraceStepResponse(
                    step_id=step.step_id,
                    expert_agent_name=step.expert_agent_name,
                    skill_id=step.skill_id,
                    status=execution.step_statuses.get(
                        step.expert_agent_name,
                        AgentExecutionStatus.PENDING,
                    ).value,
                )
                for step in plan_result.plan.steps
            ]
        ),
        artifacts=[
            ContextArtifactSummaryResponse(
                artifact_id=artifact.artifact_id,
                artifact_type=artifact.artifact_type,
                producer_agent=artifact.producer_agent,
                payload_hash=artifact.payload_hash,
            )
            for artifact in execution.artifacts
        ],
        references=[
            dict(reference)
            for reference in execution.references
        ],
    )


def _execute_user_qna_plan(
    *,
    request: UserQnaRunRequest,
    run_id: str,
    plan_steps: tuple[AgentStep, ...],
    runtime: MainAgentRuntime,
    services: DashboardServiceBundle,
    strategy_service: StrategyService,
    llm_provider_factory: Callable[[], LLMProvider],
) -> _UserQnaExecution:
    """Execute ExpertAgents selected by MainAgent for a user Q&A run."""
    answer = ""
    step_statuses: dict[str, AgentExecutionStatus] = {}
    artifacts: list[ContextArtifact] = []
    references: list[dict[str, str]] = []

    for step in plan_steps:
        if step.expert_agent_name == GeneralQnaAgent.name:
            try:
                result = GeneralQnaAgent(
                    llm_provider=llm_provider_factory(),
                    write_context_artifact=runtime.add_context_artifact,
                ).answer_general_question(
                    run_id=run_id,
                    message=request.message,
                    language=request.language,
                    available_artifacts=tuple(artifacts),
                )
            except RuntimeError as exc:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={
                        "code": "llm_unavailable",
                        "message": str(exc),
                    },
                ) from exc
            answer = result.answer
            step_statuses[step.expert_agent_name] = result.status
            artifacts.extend(result.artifacts)
            references.extend(result.references)
            continue

        if step.expert_agent_name == DataAnalystAgent.name:
            scope_version_id = _resolve_scope_alias(
                request.scope_version_id,
                strategy_service=strategy_service,
            )
            try:
                result = DataAnalystAgent(
                    llm_provider=llm_provider_factory(),
                    write_context_artifact=runtime.add_context_artifact,
                ).answer_recommendation_question(
                    run_id=run_id,
                    message=request.message,
                    scope_version_id=scope_version_id,
                    universe=request.universe,
                    language=request.language,
                    services=services,
                )
            except RuntimeError as exc:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={
                        "code": "llm_unavailable",
                        "message": str(exc),
                    },
                ) from exc
            answer = result.answer
            step_statuses[step.expert_agent_name] = result.status
            artifacts.extend(result.artifacts)
            references.extend(result.references)
            continue

        step_statuses[step.expert_agent_name] = AgentExecutionStatus.PARTIAL

    if not answer:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "agent_plan_not_executable",
                "message": "MainAgent produced no executable Q&A expert step.",
            },
        )

    return _UserQnaExecution(
        answer=answer,
        step_statuses=step_statuses,
        artifacts=tuple(artifacts),
        references=tuple(references),
    )


@router.get(
    "/agent-schedules/stock-analysis",
    response_model=StockAnalysisScheduleResponse,
)
def get_stock_analysis_schedule(repository: ScheduleRepo) -> StockAnalysisScheduleResponse:
    """Return the persisted daily stock-analysis schedule."""
    return _schedule_to_response(repository.get_stock_analysis_schedule())


@router.put(
    "/agent-schedules/stock-analysis",
    response_model=StockAnalysisScheduleResponse,
)
def update_stock_analysis_schedule(
    request: StockAnalysisScheduleUpdate,
    repository: ScheduleRepo,
    _actor_id: Annotated[str, Depends(require_local_admin)],
) -> StockAnalysisScheduleResponse:
    """Update the persisted daily stock-analysis schedule."""
    now = datetime.now(UTC)
    schedule = StockAnalysisSchedule(
        enabled=request.enabled,
        hour=request.hour,
        minute=request.minute,
        timezone=request.timezone,
        scope_version_id=request.scope_version_id,
        universe=request.universe,
        updated_at=now,
    )
    return _schedule_to_response(repository.save_stock_analysis_schedule(schedule))


def _schedule_to_response(
    schedule: StockAnalysisSchedule,
) -> StockAnalysisScheduleResponse:
    """Convert a schedule model to HTTP response."""
    return StockAnalysisScheduleResponse(
        schedule_id=schedule.schedule_id,
        run_type=schedule.run_type,
        enabled=schedule.enabled,
        hour=schedule.hour,
        minute=schedule.minute,
        timezone=schedule.timezone,
        scope_version_id=schedule.scope_version_id,
        universe=schedule.universe,
        last_triggered_at=schedule.last_triggered_at,
        next_run_at=schedule.next_run_at,
        updated_at=schedule.updated_at,
    )


def _resolve_scope_alias(
    scope_version_id: str,
    *,
    strategy_service: StrategyService,
    owner_id: str = "local-admin",
) -> str:
    """Resolve user-facing scope aliases to persisted scope version IDs."""
    if scope_version_id != "scope-current":
        return scope_version_id
    try:
        scope = strategy_service.ensure_current_research_scope(owner_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "service_not_configured",
                "message": "active research scope not found",
            },
        ) from exc
    return str(scope.version_id)
