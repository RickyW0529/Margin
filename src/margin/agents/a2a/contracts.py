"""Transport-neutral contracts for synchronous A2A dispatch."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from a2a.types import (
    AgentCard,
    Artifact,
    Message,
    SendMessageRequest,
    SendMessageResponse,
    Task,
    TaskState,
    TaskStatus,
)

from margin.agents.a2a.data import read_message_data

_RESULT_STATES = frozenset(
    {
        TaskState.TASK_STATE_COMPLETED,
        TaskState.TASK_STATE_FAILED,
        TaskState.TASK_STATE_CANCELED,
        TaskState.TASK_STATE_INPUT_REQUIRED,
        TaskState.TASK_STATE_REJECTED,
        TaskState.TASK_STATE_AUTH_REQUIRED,
    }
)


@dataclass(frozen=True, slots=True)
class AgentCall:
    """One normalized ``message/send`` invocation delivered to an agent."""

    source_agent: str
    target_agent: str
    protocol_version: str
    request: SendMessageRequest

    @property
    def message(self) -> Message:
        """Return the official A2A message carried by this call."""
        return self.request.message

    @property
    def payloads(self) -> tuple[Any, ...]:
        """Return all decoded structured data parts in message order."""
        return read_message_data(self.message)


@dataclass(frozen=True, slots=True)
class AgentResult:
    """Task output returned by a synchronous in-process agent handler."""

    artifacts: tuple[Artifact, ...] = ()
    state: int = TaskState.TASK_STATE_COMPLETED
    status_message: Message | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.state not in _RESULT_STATES:
            raise ValueError("AgentResult must use a terminal or interrupted task state")


AgentHandler = Callable[[AgentCall], AgentResult]


class A2ATransport(Protocol):
    """Replaceable synchronous transport used by ``SyncA2AClient``."""

    def register(self, card: AgentCard, handler: AgentHandler) -> None:
        """Register one addressable agent endpoint."""

    def discover_agent(self, agent_name: str) -> AgentCard:
        """Return one agent's official A2A card."""

    def list_agents(self) -> tuple[AgentCard, ...]:
        """Return all discoverable agent cards."""

    def send_message(
        self,
        target_agent: str,
        request: SendMessageRequest,
        *,
        source_agent: str,
        protocol_version: str,
    ) -> SendMessageResponse:
        """Execute A2A ``message/send`` against the target endpoint."""

    def get_task(self, task_id: str) -> Task:
        """Return the latest task snapshot."""

    def get_task_status_history(self, task_id: str) -> tuple[TaskStatus, ...]:
        """Return immutable snapshots of the task's state transitions."""
