"""Dependency-aware executor for planner-produced step DAGs."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol, TypeVar, runtime_checkable


class DAGValidationError(ValueError):
    """Raised when a plan is not a valid directed acyclic graph."""


class DAGNodeStatus(StrEnum):
    """Terminal status for one plan step."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class DAGExecutionStatus(StrEnum):
    """Aggregate status for one DAG execution."""

    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"


@runtime_checkable
class DAGStepLike(Protocol):
    """Structural contract accepted by :class:`PlanDAGExecutor`."""

    @property
    def step_id(self) -> str:
        """Stable node identity."""
        ...

    @property
    def depends_on(self) -> Sequence[str]:
        """Upstream node identities."""
        ...


@dataclass(frozen=True)
class DAGStep:
    """Generic plan step with an optional executor-specific payload."""

    step_id: str
    depends_on: tuple[str, ...] = ()
    payload: Any = None


@dataclass(frozen=True)
class DAGStepRunResult:
    """Optional structured value returned by a step runner."""

    status: DAGNodeStatus = DAGNodeStatus.SUCCEEDED
    output: Any = None
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class DAGNodeResult:
    """Structured terminal result for one plan step."""

    step_id: str
    status: DAGNodeStatus
    output: Any = None
    error_code: str | None = None
    error_message: str | None = None
    failed_dependency_ids: tuple[str, ...] = ()
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @property
    def succeeded(self) -> bool:
        """Return whether this node completed successfully."""
        return self.status is DAGNodeStatus.SUCCEEDED

    @property
    def duration_ms(self) -> float | None:
        """Return wall-clock duration when the node was executed."""
        if self.started_at is None or self.finished_at is None:
            return None
        return (self.finished_at - self.started_at).total_seconds() * 1000


@dataclass(frozen=True)
class DAGExecutionResult:
    """Aggregate DAG result in the original plan order."""

    status: DAGExecutionStatus
    results: tuple[DAGNodeResult, ...]
    started_at: datetime
    finished_at: datetime

    @property
    def step_results(self) -> tuple[DAGNodeResult, ...]:
        """Compatibility alias with an explicit plan-oriented name."""
        return self.results

    @property
    def result_by_step_id(self) -> dict[str, DAGNodeResult]:
        """Return results keyed by step identity."""
        return {result.step_id: result for result in self.results}

    @property
    def succeeded(self) -> bool:
        """Return whether every plan step succeeded."""
        return self.status is DAGExecutionStatus.SUCCEEDED


StepT = TypeVar("StepT", bound=DAGStepLike)
StepRunner = Callable[[StepT], Any]


class PlanDAGExecutor:
    """Validate and execute planner steps as a dependency DAG.

    Ready nodes are submitted immediately, so unrelated branches can run in
    parallel. A node is skipped once all of its dependencies are terminal and
    at least one dependency did not succeed.
    """

    def __init__(self, *, max_concurrency: int | None = None) -> None:
        if max_concurrency is not None and max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        self._max_concurrency = max_concurrency

    def validate(self, steps: Sequence[DAGStepLike]) -> None:
        """Validate step identities, references, and acyclicity."""
        normalized = tuple(steps)
        if not normalized:
            return
        step_ids = [_step_id(step) for step in normalized]
        if len(step_ids) != len(set(step_ids)):
            duplicates = _duplicates(step_ids)
            raise DAGValidationError("duplicate step_id: " + ", ".join(duplicates))
        known_ids = set(step_ids)
        dependencies: dict[str, tuple[str, ...]] = {}
        for step in normalized:
            step_id = _step_id(step)
            depends_on = _depends_on(step)
            if len(depends_on) != len(set(depends_on)):
                raise DAGValidationError(f"duplicate dependency for step {step_id}")
            unknown = tuple(dependency for dependency in depends_on if dependency not in known_ids)
            if unknown:
                raise DAGValidationError(
                    f"unknown dependencies for step {step_id}: " + ", ".join(unknown)
                )
            dependencies[step_id] = depends_on
        cyclic_ids = _cyclic_step_ids(step_ids, dependencies)
        if cyclic_ids:
            raise DAGValidationError("cycle detected: " + ", ".join(cyclic_ids))

    def execute(
        self,
        steps: Sequence[StepT],
        runner: StepRunner[StepT],
    ) -> DAGExecutionResult:
        """Execute a validated plan and return deterministic structured results."""
        plan = tuple(steps)
        self.validate(plan)
        started_at = datetime.now(UTC)
        if not plan:
            return DAGExecutionResult(
                status=DAGExecutionStatus.SUCCEEDED,
                results=(),
                started_at=started_at,
                finished_at=datetime.now(UTC),
            )

        step_by_id = {_step_id(step): step for step in plan}
        order = {step_id: index for index, step_id in enumerate(step_by_id)}
        dependencies = {step_id: _depends_on(step) for step_id, step in step_by_id.items()}
        dependents: dict[str, list[str]] = {step_id: [] for step_id in step_by_id}
        for step_id, dependency_ids in dependencies.items():
            for dependency_id in dependency_ids:
                dependents[dependency_id].append(step_id)

        results: dict[str, DAGNodeResult] = {}
        submitted: set[str] = set()
        ready = deque(step_id for step_id in step_by_id if not dependencies[step_id])
        worker_count = self._max_concurrency or min(32, max(1, len(plan)))

        with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="plan-dag") as pool:
            futures: dict[Future[DAGNodeResult], str] = {}
            while ready or futures:
                while ready and len(futures) < worker_count:
                    step_id = ready.popleft()
                    if step_id in submitted or step_id in results:
                        continue
                    submitted.add(step_id)
                    future = pool.submit(_run_step, step_by_id[step_id], runner)
                    futures[future] = step_id

                if not futures:
                    break
                completed, _ = wait(tuple(futures), return_when=FIRST_COMPLETED)
                for future in sorted(completed, key=lambda item: order[futures[item]]):
                    step_id = futures.pop(future)
                    try:
                        results[step_id] = future.result()
                    except Exception as exc:  # defensive: _run_step already normalizes failures
                        now = datetime.now(UTC)
                        results[step_id] = DAGNodeResult(
                            step_id=step_id,
                            status=DAGNodeStatus.FAILED,
                            error_code=type(exc).__name__,
                            error_message=str(exc),
                            started_at=now,
                            finished_at=now,
                        )
                    _release_dependents(
                        completed_step_id=step_id,
                        dependencies=dependencies,
                        dependents=dependents,
                        results=results,
                        ready=ready,
                        order=order,
                    )

        if len(results) != len(plan):
            missing = [step_id for step_id in step_by_id if step_id not in results]
            raise RuntimeError("DAG execution stalled: " + ", ".join(missing))
        ordered_results = tuple(results[_step_id(step)] for step in plan)
        return DAGExecutionResult(
            status=_aggregate_status(ordered_results),
            results=ordered_results,
            started_at=started_at,
            finished_at=datetime.now(UTC),
        )


def _run_step(step: StepT, runner: StepRunner[StepT]) -> DAGNodeResult:
    step_id = _step_id(step)
    started_at = datetime.now(UTC)
    try:
        raw_result = runner(step)
        if isinstance(raw_result, DAGNodeResult):
            if raw_result.step_id != step_id:
                raise ValueError(
                    f"runner returned result for {raw_result.step_id}, expected {step_id}"
                )
            return DAGNodeResult(
                step_id=step_id,
                status=raw_result.status,
                output=raw_result.output,
                error_code=raw_result.error_code,
                error_message=raw_result.error_message,
                failed_dependency_ids=raw_result.failed_dependency_ids,
                started_at=raw_result.started_at or started_at,
                finished_at=raw_result.finished_at or datetime.now(UTC),
            )
        if isinstance(raw_result, DAGStepRunResult):
            return DAGNodeResult(
                step_id=step_id,
                status=raw_result.status,
                output=raw_result.output,
                error_code=raw_result.error_code,
                error_message=raw_result.error_message,
                started_at=started_at,
                finished_at=datetime.now(UTC),
            )
        return DAGNodeResult(
            step_id=step_id,
            status=DAGNodeStatus.SUCCEEDED,
            output=raw_result,
            started_at=started_at,
            finished_at=datetime.now(UTC),
        )
    except Exception as exc:
        return DAGNodeResult(
            step_id=step_id,
            status=DAGNodeStatus.FAILED,
            error_code=type(exc).__name__,
            error_message=str(exc),
            started_at=started_at,
            finished_at=datetime.now(UTC),
        )


def _release_dependents(
    *,
    completed_step_id: str,
    dependencies: Mapping[str, tuple[str, ...]],
    dependents: Mapping[str, list[str]],
    results: dict[str, DAGNodeResult],
    ready: deque[str],
    order: Mapping[str, int],
) -> None:
    candidates = deque(sorted(dependents[completed_step_id], key=order.__getitem__))
    while candidates:
        step_id = candidates.popleft()
        if step_id in results or not all(dep in results for dep in dependencies[step_id]):
            continue
        failed_dependencies = tuple(
            dependency_id
            for dependency_id in dependencies[step_id]
            if not results[dependency_id].succeeded
        )
        if not failed_dependencies:
            ready.append(step_id)
            continue
        now = datetime.now(UTC)
        results[step_id] = DAGNodeResult(
            step_id=step_id,
            status=DAGNodeStatus.SKIPPED,
            error_code="upstream_failed",
            error_message="Skipped because an upstream dependency did not succeed.",
            failed_dependency_ids=failed_dependencies,
            started_at=now,
            finished_at=now,
        )
        candidates.extend(sorted(dependents[step_id], key=order.__getitem__))


def _step_id(step: DAGStepLike) -> str:
    value = step.get("step_id") if isinstance(step, Mapping) else getattr(step, "step_id", None)
    step_id = str(value or "").strip()
    if not step_id:
        raise DAGValidationError("step_id is required")
    return step_id


def _depends_on(step: DAGStepLike) -> tuple[str, ...]:
    value = (
        step.get("depends_on", ()) if isinstance(step, Mapping) else getattr(step, "depends_on", ())
    )
    if value is None:
        return ()
    if isinstance(value, str):
        raise DAGValidationError("depends_on must be a sequence of step IDs")
    return tuple(str(item).strip() for item in value)


def _duplicates(values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for value in values:
        if value in seen and value not in duplicates:
            duplicates.append(value)
        seen.add(value)
    return tuple(duplicates)


def _cyclic_step_ids(
    step_ids: Sequence[str],
    dependencies: Mapping[str, tuple[str, ...]],
) -> tuple[str, ...]:
    indegree = {step_id: len(dependencies[step_id]) for step_id in step_ids}
    dependents: dict[str, list[str]] = {step_id: [] for step_id in step_ids}
    for step_id, dependency_ids in dependencies.items():
        for dependency_id in dependency_ids:
            dependents[dependency_id].append(step_id)
    queue = deque(step_id for step_id in step_ids if indegree[step_id] == 0)
    visited: set[str] = set()
    while queue:
        step_id = queue.popleft()
        visited.add(step_id)
        for dependent_id in dependents[step_id]:
            indegree[dependent_id] -= 1
            if indegree[dependent_id] == 0:
                queue.append(dependent_id)
    return tuple(step_id for step_id in step_ids if step_id not in visited)


def _aggregate_status(results: tuple[DAGNodeResult, ...]) -> DAGExecutionStatus:
    succeeded = sum(result.succeeded for result in results)
    if succeeded == len(results):
        return DAGExecutionStatus.SUCCEEDED
    if succeeded:
        return DAGExecutionStatus.PARTIAL
    return DAGExecutionStatus.FAILED


# Short aliases make the types convenient at both planner and scheduler boundaries.
PlanStep = DAGStep
PlanStepResult = DAGNodeResult
PlanDAGResult = DAGExecutionResult
DAGExecutor = PlanDAGExecutor
