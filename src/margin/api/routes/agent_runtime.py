"""Agent runtime API routes for Q&A and scheduled stock analysis."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from margin.agent_runtime.chat_repository import (
    AgentChatRepository,
    new_chat_message,
    new_chat_session,
    summarize_messages_for_prompt,
)
from margin.agent_runtime.expert_agents import DataAnalystAgent, GeneralQnaAgent
from margin.agent_runtime.main_agent import MainAgentPlanningError, MainAgentRuntime
from margin.agent_runtime.models import AgentExecutionStatus, AgentStep, ContextArtifact
from margin.agent_runtime.schedules import (
    AgentScheduleRepository,
    StockAnalysisSchedule,
)
from margin.api.dependencies import (
    get_agent_chat_repository,
    get_agent_schedule_repository,
    get_dashboard_services,
    get_llm_provider_factory,
    get_main_agent_runtime,
    get_strategy_service,
    require_idempotency_key,
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
ChatRepo = Annotated[
    AgentChatRepository,
    Depends(get_agent_chat_repository),
]
IdempotencyKey = Annotated[str, Depends(require_idempotency_key)]


class UserQnaRunRequest(BaseModel):
    """User Q&A request routed through MainAgent."""

    model_config = ConfigDict(extra="forbid")

    scope_version_id: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=2000)
    session_id: str | None = Field(default=None, min_length=1, max_length=96)
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


class ContextArtifactDetailResponse(BaseModel):
    """Full persisted Context Store artifact detail."""

    artifact_id: str
    run_id: str
    artifact_type: str
    producer_agent: str
    payload_json: dict
    payload_hash: str
    source_refs: list[str]
    evidence_refs: list[str]
    created_at: datetime


class UserQnaRunResponse(BaseModel):
    """Response returned by the MainAgent-backed Q&A endpoint."""

    session_id: str
    user_message_id: str
    assistant_message_id: str
    run_id: str
    answer: str
    guardrail: GuardrailSummaryResponse
    agent_trace: AgentTraceResponse
    artifacts: list[ContextArtifactSummaryResponse]
    references: list[dict[str, str]]


class AgentChatSessionResponse(BaseModel):
    """One persisted chat session for the sidebar."""

    session_id: str
    title: str
    scope_version_id: str
    universe: str
    language: str
    created_at: datetime
    updated_at: datetime


class AgentChatMessageResponse(BaseModel):
    """One persisted chat message for restoring a conversation."""

    message_id: str
    session_id: str
    role: str
    content: str
    run_id: str | None
    payload: dict
    created_at: datetime


class AgentChatSessionListResponse(BaseModel):
    """Recent chat session list."""

    items: list[AgentChatSessionResponse]


class AgentChatSessionDetailResponse(BaseModel):
    """One chat session plus messages."""

    session: AgentChatSessionResponse
    messages: list[AgentChatMessageResponse]


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
    chat_repository: ChatRepo,
    services: DashboardServices,
    strategy_service: StrategyServices,
    llm_provider_factory: LLMProviderFactory,
    _idempotency_key: IdempotencyKey,
) -> UserQnaRunResponse:
    """Run a read-only user Q&A request through MainAgent-planned ExpertAgents."""
    session_id = request.session_id or f"acs_{uuid4().hex}"
    session = chat_repository.get_session(session_id)
    now = datetime.now(UTC)
    if session is None:
        if request.session_id is not None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "chat_session_not_found",
                    "message": "chat session not found",
                },
            )
        session = new_chat_session(
            session_id=session_id,
            title=_chat_title(request.message),
            scope_version_id=request.scope_version_id,
            universe=request.universe,
            language=request.language,
            now=now,
        )
        chat_repository.upsert_session(session)
    else:
        chat_repository.upsert_session(
            session.model_copy(
                update={
                    "scope_version_id": request.scope_version_id,
                    "universe": request.universe,
                    "language": request.language,
                    "updated_at": now,
                }
            )
        )

    previous_messages = chat_repository.list_messages(session_id, limit=8)
    conversation_context = summarize_messages_for_prompt(previous_messages)
    user_message_id = f"acm_{uuid4().hex}"
    chat_repository.add_message(
        new_chat_message(
            message_id=user_message_id,
            session_id=session_id,
            role="user",
            content=request.message,
            payload={
                "scope_version_id": request.scope_version_id,
                "universe": request.universe,
                "language": request.language,
            },
            now=now,
        )
    )

    run_id = f"ar_qna_{uuid4().hex}"
    try:
        plan_result = runtime.create_user_qna_plan(
            run_id=run_id,
            user_input=request.message,
            conversation_context=conversation_context,
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
        conversation_context=conversation_context,
    )

    response = UserQnaRunResponse(
        session_id=session_id,
        user_message_id=user_message_id,
        assistant_message_id=f"acm_{uuid4().hex}",
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
    chat_repository.add_message(
        new_chat_message(
            message_id=response.assistant_message_id,
            session_id=session_id,
            role="assistant",
            content=execution.answer,
            run_id=run_id,
            payload=response.model_dump(mode="json"),
        )
    )
    return response


def _execute_user_qna_plan(
    *,
    request: UserQnaRunRequest,
    run_id: str,
    plan_steps: tuple[AgentStep, ...],
    runtime: MainAgentRuntime,
    services: DashboardServiceBundle,
    strategy_service: StrategyService,
    llm_provider_factory: Callable[[], LLMProvider],
    conversation_context: list[dict[str, str]],
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
                    conversation_context=conversation_context,
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
                    conversation_context=conversation_context,
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
    "/agent-artifacts/{artifact_id}",
    response_model=ContextArtifactDetailResponse,
)
def get_agent_artifact(
    artifact_id: str,
    runtime: RuntimeDep,
) -> ContextArtifactDetailResponse:
    """Return one persisted Context Store artifact for chat-side expansion."""
    artifact = runtime.get_context_artifact(artifact_id)
    if artifact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "agent_artifact_not_found",
                "message": "agent artifact not found",
            },
        )
    return ContextArtifactDetailResponse(
        artifact_id=artifact.artifact_id,
        run_id=artifact.run_id,
        artifact_type=artifact.artifact_type,
        producer_agent=artifact.producer_agent,
        payload_json=artifact.payload_json,
        payload_hash=artifact.payload_hash,
        source_refs=list(artifact.source_refs),
        evidence_refs=list(artifact.evidence_refs),
        created_at=artifact.created_at,
    )


@router.get(
    "/agent-chat/sessions",
    response_model=AgentChatSessionListResponse,
)
def list_agent_chat_sessions(repository: ChatRepo) -> AgentChatSessionListResponse:
    """Return recent persisted user chat sessions."""
    return AgentChatSessionListResponse(
        items=[
            _chat_session_to_response(session)
            for session in repository.list_sessions(limit=20)
        ]
    )


@router.get(
    "/agent-chat/sessions/{session_id}",
    response_model=AgentChatSessionDetailResponse,
)
def get_agent_chat_session(
    session_id: str,
    repository: ChatRepo,
) -> AgentChatSessionDetailResponse:
    """Return one persisted user chat session and its messages."""
    detail = repository.get_session_detail(session_id)
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "chat_session_not_found",
                "message": "chat session not found",
            },
        )
    return AgentChatSessionDetailResponse(
        session=_chat_session_to_response(detail.session),
        messages=[
            AgentChatMessageResponse(
                message_id=message.message_id,
                session_id=message.session_id,
                role=message.role,
                content=message.content,
                run_id=message.run_id,
                payload=message.payload,
                created_at=message.created_at,
            )
            for message in detail.messages
        ],
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
    _idempotency_key: IdempotencyKey,
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


def _chat_title(message: str) -> str:
    """Return a compact session title from the first user message."""
    title = " ".join(message.strip().split())
    return title[:80] or "Untitled research chat"


def _chat_session_to_response(session) -> AgentChatSessionResponse:
    """Convert a chat session model to an API response."""
    return AgentChatSessionResponse(
        session_id=session.session_id,
        title=session.title,
        scope_version_id=session.scope_version_id,
        universe=session.universe,
        language=session.language,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )
