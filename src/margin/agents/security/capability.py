"""Capability tokens and narrowing helpers."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from margin.agents.security.policies import (
    DataAccessPolicy,
    ProductionWritePolicy,
    ToolPolicy,
)
from margin.news.models import ensure_utc


class CapabilityToken(BaseModel):
    """Run-scoped least-privilege capability token.."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    token_id: str
    run_id: str
    issued_by: str
    issued_to: str
    domain: str
    data_access: tuple[DataAccessPolicy, ...] = ()
    production_write: tuple[ProductionWritePolicy, ...] = ()
    tool_policy: tuple[ToolPolicy, ...] = ()
    allowed_artifact_types: tuple[str, ...] = ()
    allowed_tool_names: tuple[str, ...] = ()
    expires_at: datetime
    max_tool_calls: int = Field(ge=0)
    max_result_bytes: int = Field(ge=0)
    can_delegate: bool = False
    delegation_depth_remaining: int = Field(ge=0, default=0)

    @field_validator("expires_at")
    @classmethod
    def normalize_datetime(cls, value: datetime) -> datetime:
        """Normalize token timestamps to UTC.

        Args:
            value: datetime: .

        Returns:
            datetime: .
        """
        return ensure_utc(value)


def derive_capability_token(
    parent: CapabilityToken,
    *,
    token_id: str,
    issued_to: str,
    data_access: tuple[DataAccessPolicy, ...],
    production_write: tuple[ProductionWritePolicy, ...],
    tool_policy: tuple[ToolPolicy, ...],
    allowed_artifact_types: tuple[str, ...] | None = None,
    allowed_tool_names: tuple[str, ...] | None = None,
    max_tool_calls: int | None = None,
    max_result_bytes: int | None = None,
    can_delegate: bool = False,
    delegation_depth_remaining: int | None = None,
) -> CapabilityToken:
    """Derive a child token by narrowing a parent token.

    Args:
        parent: CapabilityToken: .
        token_id: str: .
        issued_to: str: .
        data_access: tuple[DataAccessPolicy, ...]: .
        production_write: tuple[ProductionWritePolicy, ...]: .
        tool_policy: tuple[ToolPolicy, ...]: .
        allowed_artifact_types: tuple[str, ...] | None: .
        allowed_tool_names: tuple[str, ...] | None: .
        max_tool_calls: int | None: .
        max_result_bytes: int | None: .

    Returns:
        CapabilityToken: .
    """
    if not parent.can_delegate or parent.delegation_depth_remaining <= 0:
        raise ValueError("capability token cannot delegate")
    _ensure_subset("data_access", data_access, parent.data_access)
    _ensure_subset("production_write", production_write, parent.production_write)
    _ensure_subset("tool_policy", tool_policy, parent.tool_policy)
    child_artifacts = allowed_artifact_types or parent.allowed_artifact_types
    child_tools = allowed_tool_names or parent.allowed_tool_names
    _ensure_subset("allowed_artifact_types", child_artifacts, parent.allowed_artifact_types)
    _ensure_subset("allowed_tool_names", child_tools, parent.allowed_tool_names)
    resolved_max_tool_calls = parent.max_tool_calls if max_tool_calls is None else max_tool_calls
    resolved_max_result_bytes = (
        parent.max_result_bytes if max_result_bytes is None else max_result_bytes
    )
    if resolved_max_tool_calls > parent.max_tool_calls:
        raise ValueError("cannot expand max_tool_calls")
    if resolved_max_result_bytes > parent.max_result_bytes:
        raise ValueError("cannot expand max_result_bytes")
    resolved_delegation_depth = (
        parent.delegation_depth_remaining - 1
        if delegation_depth_remaining is None
        else delegation_depth_remaining
    )
    if resolved_delegation_depth > parent.delegation_depth_remaining - 1:
        raise ValueError("cannot expand delegation_depth_remaining")
    if can_delegate and resolved_delegation_depth <= 0:
        raise ValueError("delegating child token requires remaining depth")
    return CapabilityToken(
        token_id=token_id,
        run_id=parent.run_id,
        issued_by=parent.issued_to,
        issued_to=issued_to,
        domain=parent.domain,
        data_access=data_access,
        production_write=production_write,
        tool_policy=tool_policy,
        allowed_artifact_types=child_artifacts,
        allowed_tool_names=child_tools,
        expires_at=parent.expires_at,
        max_tool_calls=resolved_max_tool_calls,
        max_result_bytes=resolved_max_result_bytes,
        can_delegate=can_delegate,
        delegation_depth_remaining=resolved_delegation_depth,
    )


def _ensure_subset(name: str, child: tuple, parent: tuple) -> None:
    """Process _ensure_subset.

    Args:
        name: str: .
        child: tuple: .
        parent: tuple: .

    Returns:
        None: .
    """
    if not set(child).issubset(set(parent)):
        raise ValueError(f"cannot expand {name}")
