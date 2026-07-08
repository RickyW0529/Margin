"""Layer-2 Domain ExpertAgent cards."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from margin.agents.security.policies import (
    DataAccessPolicy,
    ProductionWritePolicy,
    ToolPolicy,
)


class DomainAgentCard(BaseModel):
    """Layer-2 Domain ExpertAgent card selected by L1."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    version: str
    layer: Literal["domain"] = "domain"
    domain: str
    description: str
    worker_agent_names: tuple[str, ...]
    required_output_types: tuple[str, ...] = ()
    data_access_policy: tuple[DataAccessPolicy, ...] = ()
    production_write_policy: tuple[ProductionWritePolicy, ...] = ()
    tool_policy: tuple[ToolPolicy, ...] = ()
    max_context_tokens: int = Field(ge=1, default=6000)
