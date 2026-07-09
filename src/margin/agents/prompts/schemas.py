"""Structured output schemas for v1 prompts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class CapabilityTokenScopeSchema(BaseModel):
    """CapabilityTokenScopeSchema.."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    data_access: list[str]
    production_write: list[str]
    tool_policy: list[str]


class PlannedDomainTaskSchema(BaseModel):
    """PlannedDomainTaskSchema.."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    domain_task_id: str
    to_expert_agent: str
    skill_id: str
    objective: str
    required_output_artifact_types: list[str]
    input_artifact_refs: list[str]
    capability_token_scope: CapabilityTokenScopeSchema


class MainPlanSchema(BaseModel):
    """MainPlanSchema.."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_type: Literal["user_qna"]
    safety_decision: Literal["allow", "block", "needs_clarification", "safe_refusal"]
    user_intent: str
    domain_tasks: list[PlannedDomainTaskSchema]
    final_answer_requirements: list[str]


class WorkerResultSchema(BaseModel):
    """WorkerResultSchema.."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["succeeded", "partial", "blocked", "failed", "abstained"]
    output_artifact_refs: list[str]
    tool_call_refs: list[str]
    audit_notes: list[str]
    error_code: str | None
    retryable: bool
