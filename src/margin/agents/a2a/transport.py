"""Replaceable in-process implementation of A2A ``message/send``."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import TypeVar, cast

from a2a.helpers import new_task_from_user_message
from a2a.types import (
    AgentCard,
    Message,
    Role,
    SendMessageRequest,
    SendMessageResponse,
    Task,
    TaskState,
    TaskStatus,
)
from a2a.utils.constants import PROTOCOL_VERSION_CURRENT
from a2a.utils.errors import InvalidParamsError, TaskNotFoundError, VersionNotSupportedError
from google.protobuf.message import Message as ProtoMessage
from google.protobuf.timestamp_pb2 import Timestamp

from margin.agents.a2a.contracts import AgentCall, AgentHandler, AgentResult
from margin.agents.a2a.errors import (
    AgentExecutionError,
    DuplicateAgentError,
    DuplicateTaskError,
    UnknownAgentError,
)

IN_PROCESS_BINDING = "INPROCESS"

ProtoT = TypeVar("ProtoT", bound=ProtoMessage)


@dataclass(frozen=True, slots=True)
class _Endpoint:
    card: AgentCard
    handler: AgentHandler


class InProcessA2ATransport:
    """Thread-safe synchronous A2A transport for agents in one process."""

    def __init__(
        self,
        *,
        supported_versions: tuple[str, ...] = (PROTOCOL_VERSION_CURRENT,),
    ) -> None:
        if not supported_versions:
            raise ValueError("supported_versions cannot be empty")
        self._supported_versions = supported_versions
        self._endpoints: dict[str, _Endpoint] = {}
        self._tasks: dict[str, Task] = {}
        self._status_history: dict[str, list[TaskStatus]] = {}
        self._lock = RLock()

    def register(self, card: AgentCard, handler: AgentHandler) -> None:
        """Register an agent card and its local message handler."""
        if not card.name:
            raise InvalidParamsError("Agent card name is required")
        if not callable(handler):
            raise InvalidParamsError("Agent handler must be callable")
        if not any(
            self._has_compatible_interface(card, version)
            for version in self._supported_versions
        ):
            raise VersionNotSupportedError(
                f"Agent '{card.name}' does not advertise a compatible "
                f"{IN_PROCESS_BINDING} interface"
            )

        with self._lock:
            if card.name in self._endpoints:
                raise DuplicateAgentError(
                    f"Agent '{card.name}' is already registered",
                    data={"agent": card.name},
                )
            self._endpoints[card.name] = _Endpoint(
                card=_clone(card),
                handler=handler,
            )

    def discover_agent(self, agent_name: str) -> AgentCard:
        """Discover an agent by the name in its official A2A card."""
        with self._lock:
            endpoint = self._endpoints.get(agent_name)
            if endpoint is None:
                raise UnknownAgentError(
                    f"Agent '{agent_name}' is not registered",
                    data={"agent": agent_name},
                )
            return _clone(endpoint.card)

    def list_agents(self) -> tuple[AgentCard, ...]:
        """List discoverable cards ordered by agent name."""
        with self._lock:
            return tuple(
                _clone(self._endpoints[name].card) for name in sorted(self._endpoints)
            )

    def send_message(
        self,
        target_agent: str,
        request: SendMessageRequest,
        *,
        source_agent: str,
        protocol_version: str,
    ) -> SendMessageResponse:
        """Run one blocking A2A ``message/send`` invocation."""
        endpoint = self._resolve_endpoint(target_agent, protocol_version)
        message = self._validated_message(request)
        task = new_task_from_user_message(message)
        message.task_id = task.id
        message.context_id = task.context_id
        task.history[0].CopyFrom(message)
        task.metadata.update(
            {
                "source_agent": source_agent,
                "target_agent": target_agent,
                "protocol_version": protocol_version,
            }
        )

        self._reserve(task)
        self._transition(task, TaskState.TASK_STATE_WORKING)
        normalized_request = _clone(request)
        normalized_request.message.CopyFrom(message)
        call = AgentCall(
            source_agent=source_agent,
            target_agent=target_agent,
            protocol_version=protocol_version,
            request=normalized_request,
        )

        try:
            result = endpoint.handler(call)
            if not isinstance(result, AgentResult):
                raise TypeError("Agent handler must return AgentResult")
            task.artifacts.extend(_clone(artifact) for artifact in result.artifacts)
            if result.metadata:
                task.metadata.update(dict(result.metadata))
            self._transition(task, result.state, result.status_message)
        except Exception as exc:
            self._transition(task, TaskState.TASK_STATE_FAILED)
            raise AgentExecutionError(task, exc) from exc

        return SendMessageResponse(task=_clone(task))

    def get_task(self, task_id: str) -> Task:
        """Return a copy of the latest task snapshot."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise TaskNotFoundError(
                    f"Task '{task_id}' was not found",
                    data={"task_id": task_id},
                )
            return _clone(task)

    def get_task_status_history(self, task_id: str) -> tuple[TaskStatus, ...]:
        """Return copies of all recorded task status transitions."""
        with self._lock:
            statuses = self._status_history.get(task_id)
            if statuses is None:
                raise TaskNotFoundError(
                    f"Task '{task_id}' was not found",
                    data={"task_id": task_id},
                )
            return tuple(_clone(status) for status in statuses)

    def _resolve_endpoint(self, agent_name: str, version: str) -> _Endpoint:
        if not any(_same_protocol_major(version, item) for item in self._supported_versions):
            raise VersionNotSupportedError(
                f"A2A version '{version}' is not supported",
                data={"requested_version": version},
            )
        with self._lock:
            endpoint = self._endpoints.get(agent_name)
            if endpoint is None:
                raise UnknownAgentError(
                    f"Agent '{agent_name}' is not registered",
                    data={"agent": agent_name},
                )
            if not self._has_compatible_interface(endpoint.card, version):
                raise VersionNotSupportedError(
                    f"Agent '{agent_name}' does not support A2A version '{version}'",
                    data={"agent": agent_name, "requested_version": version},
                )
            return endpoint

    @staticmethod
    def _validated_message(request: SendMessageRequest) -> Message:
        if not request.HasField("message"):
            raise InvalidParamsError("SendMessageRequest.message is required")
        message = _clone(request.message)
        if not message.message_id:
            raise InvalidParamsError("A2A message_id is required")
        if message.role != Role.ROLE_USER:
            raise InvalidParamsError("message/send requires a ROLE_USER message")
        try:
            new_task_from_user_message(message)
        except ValueError as exc:
            raise InvalidParamsError(str(exc)) from exc
        return message

    def _has_compatible_interface(self, card: AgentCard, version: str) -> bool:
        return any(
            interface.protocol_binding.upper() == IN_PROCESS_BINDING
            and _same_protocol_major(interface.protocol_version, version)
            for interface in card.supported_interfaces
        )

    def _reserve(self, task: Task) -> None:
        status = _status(TaskState.TASK_STATE_SUBMITTED)
        task.status.CopyFrom(status)
        with self._lock:
            if task.id in self._tasks:
                raise DuplicateTaskError(
                    f"Task '{task.id}' already exists",
                    data={"task_id": task.id},
                )
            self._tasks[task.id] = _clone(task)
            self._status_history[task.id] = [_clone(status)]

    def _transition(
        self,
        task: Task,
        state: int,
        message: Message | None = None,
    ) -> None:
        status = _status(state, message)
        task.status.CopyFrom(status)
        with self._lock:
            self._tasks[task.id] = _clone(task)
            self._status_history[task.id].append(_clone(status))


def _status(state: int, message: Message | None = None) -> TaskStatus:
    timestamp = Timestamp()
    timestamp.GetCurrentTime()
    status = TaskStatus(state=state, timestamp=timestamp)
    if message is not None:
        status.message.CopyFrom(message)
    return status


def _same_protocol_major(left: str, right: str) -> bool:
    left_major = _protocol_major(left)
    right_major = _protocol_major(right)
    if left_major is None or right_major is None:
        return False
    return left_major == right_major


def _protocol_major(version: str) -> int | None:
    components = version.split(".")
    if len(components) < 2 or any(not item.isdigit() for item in components):
        return None
    return int(components[0])


def _clone(value: ProtoT) -> ProtoT:
    clone = value.__class__()
    clone.CopyFrom(value)
    return cast(ProtoT, clone)
