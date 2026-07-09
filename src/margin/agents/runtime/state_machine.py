"""Deterministic task lifecycle state machine for v1 Agent runtime."""

from __future__ import annotations

from enum import StrEnum


class TaskLifecycleState(StrEnum):
    """TaskLifecycleState.."""

    CREATED = "created"
    INPUT_GUARDRAIL_PASSED = "input_guardrail_passed"
    PLANNED = "planned"
    AUTHORIZED = "authorized"
    RUNNING = "running"
    OUTPUT_VALIDATING = "output_validating"
    AUDITING = "auditing"
    SUCCEEDED = "succeeded"
    BLOCKED = "blocked"
    FAILED = "failed"
    PARTIAL = "partial"
    ABSTAINED = "abstained"
    REPAIR_REQUIRED = "repair_required"
    RETRY_REQUIRED = "retry_required"


_TERMINAL_STATES = {
    TaskLifecycleState.SUCCEEDED,
    TaskLifecycleState.BLOCKED,
    TaskLifecycleState.FAILED,
    TaskLifecycleState.PARTIAL,
    TaskLifecycleState.ABSTAINED,
}

_ALLOWED_TRANSITIONS: dict[TaskLifecycleState, set[TaskLifecycleState]] = {
    TaskLifecycleState.CREATED: {
        TaskLifecycleState.INPUT_GUARDRAIL_PASSED,
        TaskLifecycleState.PLANNED,
        TaskLifecycleState.BLOCKED,
        TaskLifecycleState.FAILED,
    },
    TaskLifecycleState.INPUT_GUARDRAIL_PASSED: {
        TaskLifecycleState.PLANNED,
        TaskLifecycleState.BLOCKED,
        TaskLifecycleState.FAILED,
    },
    TaskLifecycleState.PLANNED: {
        TaskLifecycleState.AUTHORIZED,
        TaskLifecycleState.BLOCKED,
        TaskLifecycleState.FAILED,
    },
    TaskLifecycleState.AUTHORIZED: {
        TaskLifecycleState.RUNNING,
        TaskLifecycleState.BLOCKED,
        TaskLifecycleState.FAILED,
    },
    TaskLifecycleState.RUNNING: {
        TaskLifecycleState.OUTPUT_VALIDATING,
        TaskLifecycleState.RETRY_REQUIRED,
        TaskLifecycleState.REPAIR_REQUIRED,
        TaskLifecycleState.PARTIAL,
        TaskLifecycleState.BLOCKED,
        TaskLifecycleState.FAILED,
    },
    TaskLifecycleState.OUTPUT_VALIDATING: {
        TaskLifecycleState.AUDITING,
        TaskLifecycleState.REPAIR_REQUIRED,
        TaskLifecycleState.BLOCKED,
        TaskLifecycleState.FAILED,
    },
    TaskLifecycleState.AUDITING: {
        TaskLifecycleState.SUCCEEDED,
        TaskLifecycleState.PARTIAL,
        TaskLifecycleState.ABSTAINED,
        TaskLifecycleState.REPAIR_REQUIRED,
        TaskLifecycleState.BLOCKED,
        TaskLifecycleState.FAILED,
    },
    TaskLifecycleState.REPAIR_REQUIRED: {
        TaskLifecycleState.PLANNED,
        TaskLifecycleState.FAILED,
        TaskLifecycleState.BLOCKED,
    },
    TaskLifecycleState.RETRY_REQUIRED: {
        TaskLifecycleState.AUTHORIZED,
        TaskLifecycleState.FAILED,
        TaskLifecycleState.BLOCKED,
    },
}


class TaskStateMachine:
    """TaskStateMachine.."""

    def transition(
        self,
        current: TaskLifecycleState,
        target: TaskLifecycleState,
    ) -> TaskLifecycleState:
        """Transition.

        Args:
            current: TaskLifecycleState: .
            target: TaskLifecycleState: .

        Returns:
            TaskLifecycleState: .
        """
        if current in _TERMINAL_STATES:
            raise ValueError(f"invalid task transition from terminal state {current}")
        if target not in _ALLOWED_TRANSITIONS.get(current, set()):
            raise ValueError(f"invalid task transition: {current} -> {target}")
        return target
