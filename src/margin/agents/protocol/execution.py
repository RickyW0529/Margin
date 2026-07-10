"""Serializable execution envelopes exchanged through A2A data parts."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from margin.agent_runtime.models import ContextArtifact
from margin.agents.protocol.models import (
    ContextPack,
    DomainAuditReport,
    DomainContextCapsule,
    DomainTaskRequest,
    DomainTaskResult,
    WorkerTaskRequest,
    WorkerTaskResult,
)


class AgentRunContext(BaseModel):
    """Non-secret run context supplied to ExpertAgent and WorkerAgent endpoints."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    trigger: Literal["user_qna", "scheduled"]
    goal: str
    language: Literal["zh", "en"] = "zh"
    scope_version_id: str = ""
    universe: str = ""
    conversation_context: tuple[dict[str, str], ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def message(self) -> str:
        """Compatibility view used by existing user-Q&A worker executors."""
        return self.goal


class DomainDispatchEnvelope(BaseModel):
    """MainAgent-to-ExpertAgent structured A2A payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_context: AgentRunContext
    context_pack: ContextPack
    task: DomainTaskRequest


class WorkerDispatchEnvelope(BaseModel):
    """ExpertAgent-to-WorkerAgent structured A2A payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_context: AgentRunContext
    context_pack: ContextPack
    task: WorkerTaskRequest


class WorkerExecutionEnvelope(BaseModel):
    """WorkerAgent execution result returned to its ExpertAgent reviewer."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    result: WorkerTaskResult
    artifacts: tuple[ContextArtifact, ...] = ()
    answer: str | None = None
    table_rows: tuple[dict[str, Any], ...] = ()


class DomainExecutionEnvelope(BaseModel):
    """Expert-reviewed domain result returned to MainAgent."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    result: DomainTaskResult
    capsule: DomainContextCapsule
    audit: DomainAuditReport
    artifacts: tuple[ContextArtifact, ...] = ()
    worker_results: tuple[WorkerTaskResult, ...] = ()
    answer: str
    table_rows: tuple[dict[str, Any], ...] = ()

