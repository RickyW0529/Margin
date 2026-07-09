"""Layer-3 WorkerAgent runtime for v1 Agent protocol."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from margin.agents.protocol.models import (
    AgentExecutionStatus,
    WorkerTaskRequest,
    WorkerTaskResult,
)
from margin.agents.runtime.executor_registry import ExecutorRegistry


class WorkerRuntime:
    """WorkerRuntime.."""

    def __init__(self, *, executor_registry: ExecutorRegistry) -> None:
        """Init .

        Args:
            executor_registry: ExecutorRegistry: .

        Returns:
            None: .
        """
        self._executor_registry = executor_registry

    def execute(self, request: WorkerTaskRequest) -> WorkerTaskResult:
        """Execute.

        Args:
            request: WorkerTaskRequest: .

        Returns:
            WorkerTaskResult: .
        """
        if not self._executor_registry.has(request.worker_agent, request.skill_id):
            return WorkerTaskResult(
                run_id=request.run_id,
                domain_task_id=request.domain_task_id,
                worker_task_id=request.worker_task_id,
                worker_agent=request.worker_agent,
                skill_id=request.skill_id,
                status=AgentExecutionStatus.BLOCKED,
                error_code="executor_not_registered",
                retryable=False,
                safe_summary="Worker executor is not registered.",
            )
        executor = cast(
            Callable[[WorkerTaskRequest], WorkerTaskResult],
            self._executor_registry.get(request.worker_agent, request.skill_id),
        )
        result = executor(request)
        if result.status is AgentExecutionStatus.SUCCEEDED and not result.output_artifact_refs:
            return result.model_copy(
                update={
                    "status": AgentExecutionStatus.BLOCKED,
                    "error_code": "missing_required_artifact",
                    "retryable": False,
                    "safe_summary": "Worker succeeded without required artifacts.",
                }
            )
        return result
