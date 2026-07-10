"""Agent runtime API routes for Q&A and scheduled stock analysis."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal, Protocol
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from margin.agent_runtime.chat_repository import (
    AgentChatRepository,
    new_chat_message,
    new_chat_session,
    summarize_messages_for_prompt,
)
from margin.agent_runtime.schedules import (
    AgentScheduleRepository,
    StockAnalysisSchedule,
)
from margin.agents.runtime.service import (
    AgentInputBlockedError,
    AgentRuntimeService,
    AgentRuntimeUnavailableError,
    UserQnaCommand,
)
from margin.api.dependencies import (
    get_agent_chat_repository,
    get_agent_runtime_service,
    get_agent_schedule_repository,
    get_idempotency_store,
    require_idempotency_key,
    require_local_admin,
)
from margin.api.serialization import safe_artifact_payload
from margin.core.hashing import stable_json_hash
from margin.platform_runtime.repository import IdempotencyKeyRecord

router = APIRouter(prefix="/api/v1", tags=["agent-runtime"])

RuntimeDep = Annotated[AgentRuntimeService, Depends(get_agent_runtime_service)]
ScheduleRepo = Annotated[
    AgentScheduleRepository,
    Depends(get_agent_schedule_repository),
]
ChatRepo = Annotated[
    AgentChatRepository,
    Depends(get_agent_chat_repository),
]
IdempotencyKey = Annotated[str, Depends(require_idempotency_key)]
_USER_QNA_SCOPE = "agent.user_qna"
_WORKSPACE_QNA_SCOPE = "agent.workspace_qna"
_USER_QNA_TTL = timedelta(hours=24)


class _IdempotencyStore(Protocol):
    """Minimal store interface used by user-qna replay."""

    def get_idempotency_key(self, idempotency_key: str) -> IdempotencyKeyRecord | None:
        """Return a prior record when present."""

    def record_idempotency_key(self, record: IdempotencyKeyRecord) -> None:
        """Persist a completed request/response pair."""

    def begin_idempotency_key(
        self,
        record: IdempotencyKeyRecord,
    ) -> IdempotencyKeyRecord | None:
        """Reserve a key before side effects run."""

    def complete_idempotency_key(self, record: IdempotencyKeyRecord) -> IdempotencyKeyRecord:
        """Mark a reserved key completed."""


IdempotencyStoreDep = Annotated[Any, Depends(get_idempotency_store)]


class UserQnaRunRequest(BaseModel):
    """User Q&A request routed through MainAgent.."""

    model_config = ConfigDict(extra="forbid")

    scope_version_id: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=2000)
    session_id: str | None = Field(default=None, min_length=1, max_length=96)
    universe: str = Field(default="ALL_A", min_length=1, max_length=32)
    language: Literal["zh", "en"] = "zh"


class GuardrailSummaryResponse(BaseModel):
    """Safe guardrail summary returned to the frontend.."""

    allowed: bool
    decision: str
    summary: str
    triggered_policies: list[str] = Field(default_factory=list)


class AgentTraceStepResponse(BaseModel):
    """One user-visible expert-agent trace row.."""

    step_id: str
    expert_agent_name: str
    skill_id: str
    status: str


class AgentTraceResponse(BaseModel):
    """User-visible MainAgent trace.."""

    steps: list[AgentTraceStepResponse]


class ContextArtifactSummaryResponse(BaseModel):
    """Short Context Store artifact summary safe for the frontend.."""

    artifact_id: str
    artifact_type: str
    producer_agent: str
    payload_hash: str


class ContextArtifactDetailResponse(BaseModel):
    """Full persisted Context Store artifact detail.."""

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
    """Response returned by the MainAgent-backed Q&A endpoint.."""

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
    """One persisted chat session for the sidebar.."""

    session_id: str
    title: str
    scope_version_id: str
    universe: str
    language: str
    created_at: datetime
    updated_at: datetime


class AgentChatMessageResponse(BaseModel):
    """One persisted chat message for restoring a conversation.."""

    message_id: str
    session_id: str
    role: str
    content: str
    run_id: str | None
    payload: dict
    created_at: datetime


class AgentChatSessionListResponse(BaseModel):
    """Recent chat session list.."""

    items: list[AgentChatSessionResponse]


class AgentChatSessionDetailResponse(BaseModel):
    """One chat session plus messages.."""

    session: AgentChatSessionResponse
    messages: list[AgentChatMessageResponse]


class StockAnalysisScheduleUpdate(BaseModel):
    """Request body for updating the daily stock-analysis schedule.."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    hour: int = Field(ge=0, le=23)
    minute: int = Field(ge=0, le=59)
    timezone: str = "Asia/Shanghai"
    scope_version_id: str = Field(default="scope-current", min_length=1, max_length=64)
    universe: str = Field(default="ALL_A", min_length=1, max_length=32)


class StockAnalysisScheduleResponse(BaseModel):
    """Persisted stock-analysis schedule returned to the frontend.."""

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

@router.post("/agent-runs/user-qna", response_model=UserQnaRunResponse)
def run_user_qna_agent(
    request: UserQnaRunRequest,
    runtime: RuntimeDep,
    chat_repository: ChatRepo,
    idempotency_key: IdempotencyKey,
    idempotency_store: IdempotencyStoreDep,
) -> UserQnaRunResponse:
    """Run a read-only user Q&A request through the v1 Agent runtime service.

    Retries with the same Idempotency-Key and request body replay the stored
    response without re-executing the LLM path or appending chat messages.
    """
    return _run_user_qna_agent(
        request=request,
        runtime=runtime,
        chat_repository=chat_repository,
        idempotency_key=idempotency_key,
        idempotency_store=idempotency_store,
        idempotency_scope=_USER_QNA_SCOPE,
        allow_workspace_tools=False,
    )


@router.post("/agent-runs/workspace", response_model=UserQnaRunResponse)
def run_workspace_agent(
    request: UserQnaRunRequest,
    runtime: RuntimeDep,
    chat_repository: ChatRepo,
    idempotency_key: IdempotencyKey,
    idempotency_store: IdempotencyStoreDep,
    _actor_id: Annotated[str, Depends(require_local_admin)],
) -> UserQnaRunResponse:
    """Run an administrator-authorized request with workspace tools enabled."""
    return _run_user_qna_agent(
        request=request,
        runtime=runtime,
        chat_repository=chat_repository,
        idempotency_key=idempotency_key,
        idempotency_store=idempotency_store,
        idempotency_scope=_WORKSPACE_QNA_SCOPE,
        allow_workspace_tools=True,
    )


def _run_user_qna_agent(
    *,
    request: UserQnaRunRequest,
    runtime: AgentRuntimeService,
    chat_repository: AgentChatRepository,
    idempotency_key: str,
    idempotency_store: _IdempotencyStore,
    idempotency_scope: str,
    allow_workspace_tools: bool,
) -> UserQnaRunResponse:
    """Execute the shared Q&A lifecycle for one explicitly selected capability scope."""
    request_hash = stable_json_hash(request.model_dump(mode="json"))
    scoped_key = f"{idempotency_scope}:{idempotency_key}"
    now = datetime.now(UTC)
    pending = IdempotencyKeyRecord(
        idempotency_key=scoped_key,
        scope=idempotency_scope,
        request_hash=request_hash,
        response_hash=None,
        response_ref=None,
        status="pending",
        created_at=now,
        expires_at=now + _USER_QNA_TTL,
    )
    existing = idempotency_store.begin_idempotency_key(pending)
    if existing is not None:
        if existing.request_hash != request_hash:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "idempotency_key_conflict",
                    "message": "Idempotency-Key was reused with a different request body",
                },
            )
        if existing.status == "completed" and existing.response_ref:
            return UserQnaRunResponse.model_validate_json(existing.response_ref)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "idempotency_key_in_progress",
                "message": "Idempotency-Key is already processing this request",
            },
        )

    session_id = request.session_id or f"acs_{uuid4().hex}"
    session = chat_repository.get_session(session_id)
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
        execution = runtime.run_user_qna(
            UserQnaCommand(
                run_id=run_id,
                scope_version_id=request.scope_version_id,
                message=request.message,
                universe=request.universe,
                language=request.language,
                conversation_context=tuple(conversation_context),
                allow_workspace_tools=allow_workspace_tools,
            )
        )
    except AgentInputBlockedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "agent_guardrail_blocked",
                "message": exc.guardrail.summary,
                "triggered_policies": list(exc.guardrail.triggered_policies),
            },
        ) from exc
    except AgentRuntimeUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "agent_runtime_unavailable",
                "message": str(exc),
            },
        ) from exc

    response = UserQnaRunResponse(
        session_id=session_id,
        user_message_id=user_message_id,
        assistant_message_id=f"acm_{uuid4().hex}",
        run_id=run_id,
        answer=execution.answer,
        guardrail=GuardrailSummaryResponse(
            allowed=execution.guardrail.allowed,
            decision=execution.guardrail.decision,
            summary=execution.guardrail.summary,
            triggered_policies=list(execution.guardrail.triggered_policies),
        ),
        agent_trace=AgentTraceResponse(
            steps=[
                AgentTraceStepResponse(
                    step_id=step.step_id,
                    expert_agent_name=step.expert_agent_name,
                    skill_id=step.skill_id,
                    status=step.status.value,
                )
                for step in execution.trace_steps
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
        references=[dict(reference) for reference in execution.references],
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
    response_payload = response.model_dump_json()
    record = IdempotencyKeyRecord(
        idempotency_key=scoped_key,
        scope=idempotency_scope,
        request_hash=request_hash,
        response_hash=stable_json_hash(json.loads(response_payload)),
        response_ref=response_payload,
        status="completed",
        created_at=now,
        expires_at=now + _USER_QNA_TTL,
    )
    try:
        completed = idempotency_store.complete_idempotency_key(record)
    except ValueError:
        # Concurrent writer won; if the request matches, return the stored response.
        raced = idempotency_store.get_idempotency_key(scoped_key)
        if (
            raced is not None
            and raced.request_hash == request_hash
            and raced.status == "completed"
            and raced.response_ref
        ):
            return UserQnaRunResponse.model_validate_json(raced.response_ref)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "idempotency_key_conflict",
                "message": "Idempotency-Key was reused with a different request body",
            },
        ) from None
    if completed.status == "completed" and completed.response_ref != response_payload:
        return UserQnaRunResponse.model_validate_json(completed.response_ref or response_payload)
    return response


@router.get(
    "/agent-artifacts/{artifact_id}",
    response_model=ContextArtifactDetailResponse,
)
def get_agent_artifact(
    artifact_id: str,
    runtime: RuntimeDep,
) -> ContextArtifactDetailResponse:
    """Return one persisted Context Store artifact for chat-side expansion.

    Args:
        artifact_id: str: .
        runtime: RuntimeDep: .

    Returns:
        ContextArtifactDetailResponse: .
    """
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
        payload_json=safe_artifact_payload(artifact.payload_json),
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
    """Return recent persisted user chat sessions.

    Args:
        repository: ChatRepo: .

    Returns:
        AgentChatSessionListResponse: .
    """
    return AgentChatSessionListResponse(
        items=[_chat_session_to_response(session) for session in repository.list_sessions(limit=20)]
    )


@router.get(
    "/agent-chat/sessions/{session_id}",
    response_model=AgentChatSessionDetailResponse,
)
def get_agent_chat_session(
    session_id: str,
    repository: ChatRepo,
) -> AgentChatSessionDetailResponse:
    """Return one persisted user chat session and its messages.

    Args:
        session_id: str: .
        repository: ChatRepo: .

    Returns:
        AgentChatSessionDetailResponse: .
    """
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
    """Return the persisted daily stock-analysis schedule.

    Args:
        repository: ScheduleRepo: .

    Returns:
        StockAnalysisScheduleResponse: .
    """
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
    """Update the persisted daily stock-analysis schedule.

    Args:
        request: StockAnalysisScheduleUpdate: .
        repository: ScheduleRepo: .
        _idempotency_key: IdempotencyKey: .
        _actor_id: Annotated[str, Depends(require_local_admin)]: .

    Returns:
        StockAnalysisScheduleResponse: .
    """
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
    """Convert a schedule model to HTTP response.

    Args:
        schedule: StockAnalysisSchedule: .

    Returns:
        StockAnalysisScheduleResponse: .
    """
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


def _chat_title(message: str) -> str:
    """Return a compact session title from the first user message.

    Args:
        message: str: .

    Returns:
        str: .
    """
    title = " ".join(message.strip().split())
    return title[:80] or "Untitled research chat"


def _chat_session_to_response(session) -> AgentChatSessionResponse:
    """Convert a chat session model to an API response.

    Args:
        session: Any: .

    Returns:
        AgentChatSessionResponse: .
    """
    return AgentChatSessionResponse(
        session_id=session.session_id,
        title=session.title,
        scope_version_id=session.scope_version_id,
        universe=session.universe,
        language=session.language,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )
