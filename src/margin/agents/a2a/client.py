"""Synchronous facade over replaceable A2A transports."""

from __future__ import annotations

from typing import Any

from a2a.helpers import new_data_message
from a2a.types import (
    AgentCard,
    Message,
    Role,
    SendMessageRequest,
    Task,
    TaskStatus,
)
from a2a.utils.constants import PROTOCOL_VERSION_CURRENT
from a2a.utils.errors import InvalidAgentResponseError

from margin.agents.a2a.contracts import A2ATransport
from margin.agents.a2a.data import JSON_MEDIA_TYPE, encode_data_payload


class SyncA2AClient:
    """Blocking A2A client facade used by the current synchronous runtimes."""

    def __init__(
        self,
        transport: A2ATransport,
        *,
        source_agent: str,
        protocol_version: str = PROTOCOL_VERSION_CURRENT,
    ) -> None:
        if not source_agent:
            raise ValueError("source_agent is required")
        self._transport = transport
        self._source_agent = source_agent
        self._protocol_version = protocol_version

    def discover_agent(self, agent_name: str) -> AgentCard:
        """Discover a target through the configured transport."""
        return self._transport.discover_agent(agent_name)

    def list_agents(self) -> tuple[AgentCard, ...]:
        """List all agents discoverable through the configured transport."""
        return self._transport.list_agents()

    def send_message(self, target_agent: str, message: Message) -> Task | Message:
        """Send an official A2A message and unwrap its response payload."""
        response = self._transport.send_message(
            target_agent,
            SendMessageRequest(message=message),
            source_agent=self._source_agent,
            protocol_version=self._protocol_version,
        )
        payload_kind = response.WhichOneof("payload")
        if payload_kind == "task":
            return response.task
        if payload_kind == "message":
            return response.message
        raise InvalidAgentResponseError("message/send response has no payload")

    def send_data(
        self,
        target_agent: str,
        payload: Any,
        *,
        task_id: str | None = None,
        context_id: str | None = None,
    ) -> Task:
        """Send structured data in an A2A DataPart and require a Task response."""
        message = new_data_message(
            encode_data_payload(payload),
            media_type=JSON_MEDIA_TYPE,
            context_id=context_id,
            task_id=task_id,
            role=Role.ROLE_USER,
        )
        result = self.send_message(target_agent, message)
        if not isinstance(result, Task):
            raise InvalidAgentResponseError("Structured message did not return a Task")
        return result

    def get_task(self, task_id: str) -> Task:
        """Retrieve the latest task snapshot through the transport."""
        return self._transport.get_task(task_id)

    def get_task_status_history(self, task_id: str) -> tuple[TaskStatus, ...]:
        """Retrieve task lifecycle transitions through the transport."""
        return self._transport.get_task_status_history(task_id)
