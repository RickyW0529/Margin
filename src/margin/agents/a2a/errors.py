"""Errors raised by Margin A2A transports."""

from __future__ import annotations

from a2a.types import Task
from a2a.utils.errors import A2AError


class UnknownAgentError(A2AError):
    """Raised when discovery or delivery targets an unregistered agent."""

    message = "Agent not found"


class DuplicateAgentError(A2AError):
    """Raised when an agent name is registered more than once."""

    message = "Agent already registered"


class DuplicateTaskError(A2AError):
    """Raised when a caller reuses a task identifier."""

    message = "Task already exists"


class AgentExecutionError(A2AError):
    """Raised when an in-process handler fails after its task was created."""

    message = "Agent execution failed"

    def __init__(self, task: Task, cause: Exception) -> None:
        self.task = Task()
        self.task.CopyFrom(task)
        self.cause = cause
        super().__init__(
            message=f"Agent execution failed for task '{task.id}': {cause}",
            data={"task_id": task.id},
        )
