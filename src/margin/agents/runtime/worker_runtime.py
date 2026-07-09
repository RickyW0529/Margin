"""Layer-3 WorkerAgent runtime for v1 Agent protocol."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from margin.agents.protocol.models import (
    AgentExecutionStatus,
    WorkerTaskRequest,
    WorkerTaskResult,
)
from margin.agents.runtime.execution_context import (
    WorkerExecutionBundle,
    WorkerExecutionContext,
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

    def execute(
        self,
        request: WorkerTaskRequest,
        context: WorkerExecutionContext | None = None,
    ) -> WorkerTaskResult | WorkerExecutionBundle:
        """Execute.

        Args:
            request: WorkerTaskRequest: .

        Returns:
            WorkerTaskResult | WorkerExecutionBundle: .
        """
        if not self._executor_registry.has(request.worker_agent, request.skill_id):
            result = _blocked_result(
                request,
                error_code="executor_not_registered",
                summary="Worker executor is not registered.",
            )
            if context is not None:
                return _bundle_from_result(result)
            return result
        executor = self._executor_registry.get(request.worker_agent, request.skill_id)
        if context is not None:
            bundle = _execute_bundle(executor, request, context)
            return _bundle_with_validated_result(bundle)
        legacy_executor = cast(Callable[[WorkerTaskRequest], WorkerTaskResult], executor)
        result = legacy_executor(request)
        return _validated_result(result)


def _execute_bundle(
    executor: object,
    request: WorkerTaskRequest,
    context: WorkerExecutionContext,
) -> WorkerExecutionBundle:
    execute = getattr(executor, "execute", None)
    if callable(execute):
        return cast(WorkerExecutionBundle, execute(request, context))
    if callable(executor):
        result = cast(Callable[[WorkerTaskRequest], WorkerTaskResult], executor)(request)
        return _bundle_from_result(result)
    return _bundle_from_result(
        _blocked_result(
            request,
            error_code="executor_not_callable",
            summary="Worker executor is not callable.",
        )
    )


def _bundle_with_validated_result(bundle: WorkerExecutionBundle) -> WorkerExecutionBundle:
    result = _validated_result(bundle.result)
    if result is bundle.result:
        return bundle
    return WorkerExecutionBundle(
        result=result,
        artifacts=bundle.artifacts,
        answer=None,
        table_rows=bundle.table_rows,
    )


def _validated_result(result: WorkerTaskResult) -> WorkerTaskResult:
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


def _bundle_from_result(result: WorkerTaskResult) -> WorkerExecutionBundle:
    return WorkerExecutionBundle(result=result, artifacts=(), answer=None, table_rows=[])


def _blocked_result(
    request: WorkerTaskRequest,
    *,
    error_code: str,
    summary: str,
) -> WorkerTaskResult:
    return WorkerTaskResult(
        run_id=request.run_id,
        domain_task_id=request.domain_task_id,
        worker_task_id=request.worker_task_id,
        worker_agent=request.worker_agent,
        skill_id=request.skill_id,
        status=AgentExecutionStatus.BLOCKED,
        error_code=error_code,
        retryable=False,
        safe_summary=summary,
    )
