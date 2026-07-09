"""Runtime context passed to registered WorkerAgent executors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from margin.agent_runtime.context_store import AgentContextStore, ContextArtifact
from margin.agents.context.repository import ContextRepository
from margin.agents.protocol.models import ContextPack, WorkerTaskResult
from margin.agents.security.capability import CapabilityToken
from margin.agents.tools.gateway import ToolGateway
from margin.research.llm import LLMProvider


@dataclass(frozen=True)
class WorkerExecutionContext:
    """Bounded context available to one WorkerAgent executor."""

    command: Any
    context_pack: ContextPack
    context_store: AgentContextStore
    context_repository: ContextRepository
    tool_gateway: ToolGateway | None
    capability_token: CapabilityToken | None
    llm_provider_factory: Callable[[], LLMProvider]


@dataclass(frozen=True)
class WorkerExecutionBundle:
    """Executed WorkerAgent result plus frontend-safe artifacts."""

    result: WorkerTaskResult
    artifacts: tuple[ContextArtifact, ...]
    answer: str | None
    table_rows: list[dict[str, Any]]
