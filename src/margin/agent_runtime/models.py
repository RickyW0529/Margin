"""Domain models for the v0.4 agent runtime."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AgentRunType(StrEnum):
    """Agent run types."""

    SCHEDULED_STOCK_ANALYSIS = "scheduled_stock_analysis"
    MANUAL_REFRESH = "manual_refresh"
    USER_QNA = "user_qna"


class AgentPermissionMode(StrEnum):
    """Permission mode for an agent run."""

    READ_ONLY = "read_only"
    WRITE_ALLOWED = "write_allowed"


class AgentExecutionStatus(StrEnum):
    """Common execution status."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    FAILED = "failed"


class GuardrailStage(StrEnum):
    """Guardrail stages."""

    INPUT = "input"
    PLAN = "plan"
    TOOL = "tool"
    OUTPUT = "output"
    FINAL = "final"


class GuardrailDecision(BaseModel):
    """Structured guardrail decision for an agent run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_id: str
    guardrail_id: str = ""
    run_id: str
    stage: GuardrailStage
    policy_version: str = ""
    decision: str = "allow"
    allowed: bool
    evaluation_summary: str
    triggered_policies: tuple[str, ...] = ()
    input_hash: str = ""
    output_hash: str = ""
    safe_summary: str = ""
    user_message: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RetryPolicy(BaseModel):
    """Retry policy declared by a fixed-flow step."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_attempts: int = Field(ge=1)
    retryable_statuses: tuple[AgentExecutionStatus, ...] = ()


class FrontendProjection(BaseModel):
    """Frontend label metadata for a flow step."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str
    visible: bool


class AgentStepDefinition(BaseModel):
    """One fixed-flow step definition."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    step_id: str
    order: int = Field(ge=1)
    expert_agent: str
    skill_id: str
    description: str = ""
    required_artifacts: tuple[str, ...] = ()
    produced_artifacts: tuple[str, ...] = ()
    guardrails: tuple[GuardrailStage, ...]
    retry_policy: RetryPolicy
    frontend_projection: FrontendProjection


class AgentFlowDefinition(BaseModel):
    """Fixed or dynamic flow definition."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    flow_id: str
    version: str
    run_type: AgentRunType
    fixed_flow: bool
    permission_mode: AgentPermissionMode
    description: str = ""
    steps: tuple[AgentStepDefinition, ...]

    def ordered_steps(self) -> tuple[AgentStepDefinition, ...]:
        """Return steps ordered by explicit order."""
        return tuple(sorted(self.steps, key=lambda step: step.order))


class AgentRun(BaseModel):
    """One agent runtime run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    run_type: AgentRunType
    status: AgentExecutionStatus
    permission_mode: AgentPermissionMode
    trigger_source: str
    user_intent_summary: str = ""
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None


class AgentStep(BaseModel):
    """One planned or executed agent step."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    step_id: str
    run_id: str
    expert_agent_name: str
    skill_id: str
    status: AgentExecutionStatus
    input_artifact_refs: tuple[str, ...] = ()
    output_artifact_refs: tuple[str, ...] = ()
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None


class ContextArtifact(BaseModel):
    """Artifact written to the Shared Context Store."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_id: str
    run_id: str
    artifact_type: str
    producer_agent: str
    payload_json: dict[str, Any]
    payload_hash: str
    source_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AgentSkill(BaseModel):
    """One skill exposed on an ExpertAgent card."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    skill_id: str
    name: str
    description: str
    input_modes: tuple[str, ...] = ("text",)
    output_modes: tuple[str, ...] = ("json",)
    tags: tuple[str, ...] = ()
    required_context_artifacts: tuple[str, ...] = ()
    produced_context_artifacts: tuple[str, ...] = ()
    write_policy: AgentPermissionMode = AgentPermissionMode.READ_ONLY
    schedule_allowed: bool = False
    qa_allowed: bool = True


class AgentCard(BaseModel):
    """A2A-style ExpertAgent card exposed to MainAgent."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    description: str
    url: str
    version: str
    capabilities: dict[str, object]
    authentication: dict[str, object]
    default_input_modes: tuple[str, ...] = ("text",)
    default_output_modes: tuple[str, ...] = ("json",)
    skills: tuple[AgentSkill, ...]


class AgentPlan(BaseModel):
    """MainAgent plan."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    plan_id: str
    run_id: str
    fixed_flow: bool
    steps: tuple[AgentStep, ...]


class MainAgentPlanResult(BaseModel):
    """Result of MainAgent planning."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    plan: AgentPlan
    guardrail_decision: GuardrailDecision


class MainAgentReviewResult(BaseModel):
    """Result of MainAgent final review."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: str
    summary: str
    missing_artifacts: tuple[str, ...] = ()
    expert_to_retry: str | None = None
    skill_to_retry: str | None = None
    frontend_trace_summary: tuple[str, ...] = ()
