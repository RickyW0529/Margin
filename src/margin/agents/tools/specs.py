"""Tool protocol models for the v1 Agent ToolGateway."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from margin.agents.security.capability import CapabilityToken
from margin.agents.security.policies import (
    DataAccessPolicy,
    ProductionWritePolicy,
    ToolPolicy,
)


class ToolCallStatus(StrEnum):
    """ToolCallStatus.."""

    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    FAILED = "failed"


class ToolSpec(BaseModel):
    """ToolSpec.."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_name: str
    tool_version: str
    description: str
    owner_domain: str
    input_schema_ref: str
    output_schema_ref: str
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    required_data_access: tuple[DataAccessPolicy, ...] = ()
    required_write_policy: tuple[ProductionWritePolicy, ...] = ()
    required_tool_policy: tuple[ToolPolicy, ...] = ()
    idempotent: bool
    mutates_state: bool
    timeout_ms: int = Field(ge=1)
    max_output_bytes: int = Field(ge=1)
    returns_raw_payload: bool = False
    allowed_runtimes: tuple[str, ...] = ()


class ToolCallRequest(BaseModel):
    """ToolCallRequest.."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_call_id: str
    run_id: str
    task_id: str
    caller_agent: str
    tool_name: str
    tool_version: str
    input_json: dict[str, Any]
    capability_token: CapabilityToken
    context_pack_id: str | None = None
    context_pack_hash: str | None = None
    idempotency_key: str
    deadline_ms: int = Field(ge=1)


class ToolCallResult(BaseModel):
    """ToolCallResult.."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_call_id: str
    status: ToolCallStatus
    output_json: dict[str, Any] | None = None
    output_artifact_refs: tuple[str, ...] = ()
    audit_ref: str
    error_code: str | None = None
    retryable: bool = False
