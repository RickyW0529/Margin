"""Layer-3 WorkerAgent cards."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from margin.agents.security.policies import (
    DataAccessPolicy,
    ProductionWritePolicy,
    ToolPolicy,
)


class RetryPolicy(BaseModel):
    """Worker retry policy.."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_attempts: int = Field(ge=1, default=1)
    retryable_statuses: tuple[str, ...] = ()


class WorkerSkill(BaseModel):
    """One executable or planned WorkerAgent skill.."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    skill_id: str
    description: str
    input_artifact_types: tuple[str, ...] = ()
    output_artifact_types: tuple[str, ...] = ()
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    deterministic: bool = False
    planned_only: bool = False


class WorkerAgentCard(BaseModel):
    """Layer-3 WorkerAgent card visible only through an executor registry.."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    version: str
    layer: Literal["worker"] = "worker"
    domain: str
    description: str
    skills: tuple[WorkerSkill, ...]
    supported_runtimes: tuple[
        Literal["deterministic", "langgraph", "python"],
        ...,
    ] = ("deterministic",)
    data_access_policy: tuple[DataAccessPolicy, ...] = ()
    production_write_policy: tuple[ProductionWritePolicy, ...] = ()
    tool_policy: tuple[ToolPolicy, ...] = ()
    max_context_tokens: int = Field(ge=1, default=4096)
    max_tool_calls: int = Field(ge=0, default=0)
    requires_human_confirmation: bool = False
