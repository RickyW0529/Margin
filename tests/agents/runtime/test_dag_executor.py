"""Unit tests for the generic planner DAG executor."""

from __future__ import annotations

from threading import Barrier, Lock

import pytest

from margin.agents.runtime.dag import (
    DAGExecutionStatus,
    DAGNodeStatus,
    DAGStep,
    DAGValidationError,
    PlanDAGExecutor,
)


def test_dag_executes_out_of_order_steps_after_dependencies() -> None:
    execution_order: list[str] = []
    steps = (
        DAGStep(step_id="publish", depends_on=("load",)),
        DAGStep(step_id="load"),
    )

    result = PlanDAGExecutor(max_concurrency=2).execute(
        steps,
        lambda step: execution_order.append(step.step_id) or step.step_id,
    )

    assert execution_order == ["load", "publish"]
    assert [item.step_id for item in result.results] == ["publish", "load"]
    assert result.status is DAGExecutionStatus.SUCCEEDED


def test_dag_runs_independent_steps_in_parallel() -> None:
    rendezvous = Barrier(2, timeout=1)
    active = 0
    peak_active = 0
    lock = Lock()

    def run(step: DAGStep) -> str:
        nonlocal active, peak_active
        with lock:
            active += 1
            peak_active = max(peak_active, active)
        rendezvous.wait()
        with lock:
            active -= 1
        return step.step_id

    result = PlanDAGExecutor(max_concurrency=2).execute(
        (DAGStep("left"), DAGStep("right")),
        run,
    )

    assert result.succeeded is True
    assert peak_active == 2


def test_dag_skips_transitive_dependents_after_failure() -> None:
    executed: list[str] = []

    def run(step: DAGStep) -> str:
        executed.append(step.step_id)
        if step.step_id == "load":
            raise RuntimeError("source unavailable")
        return step.step_id

    result = PlanDAGExecutor(max_concurrency=3).execute(
        (
            DAGStep("verify", depends_on=("transform",)),
            DAGStep("independent"),
            DAGStep("transform", depends_on=("load",)),
            DAGStep("load"),
        ),
        run,
    )

    by_id = result.result_by_step_id
    assert by_id["load"].status is DAGNodeStatus.FAILED
    assert by_id["transform"].status is DAGNodeStatus.SKIPPED
    assert by_id["transform"].failed_dependency_ids == ("load",)
    assert by_id["verify"].status is DAGNodeStatus.SKIPPED
    assert by_id["verify"].failed_dependency_ids == ("transform",)
    assert by_id["independent"].status is DAGNodeStatus.SUCCEEDED
    assert set(executed) == {"load", "independent"}
    assert result.status is DAGExecutionStatus.PARTIAL


def test_dag_rejects_unknown_dependencies() -> None:
    with pytest.raises(DAGValidationError, match="unknown dependencies"):
        PlanDAGExecutor().execute(
            (DAGStep("publish", depends_on=("missing",)),),
            lambda step: step.step_id,
        )


def test_dag_rejects_cycles() -> None:
    with pytest.raises(DAGValidationError, match="cycle detected"):
        PlanDAGExecutor().execute(
            (
                DAGStep("left", depends_on=("right",)),
                DAGStep("right", depends_on=("left",)),
            ),
            lambda step: step.step_id,
        )
