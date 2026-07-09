"""Planning action protocol shared by MainAgent and ExpertAgent."""

from __future__ import annotations

from enum import StrEnum


class PlanActionKind(StrEnum):
    """Allowed planner action kinds."""

    EXECUTE = "execute"
    DELEGATE = "delegate"
    INSPECT_CONTEXT = "inspect_context"
    ASK_CLARIFICATION = "ask_clarification"
    BLOCKED = "blocked"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    SYNTHESIZE = "synthesize"


NON_EXECUTION_KINDS = {
    PlanActionKind.ASK_CLARIFICATION,
    PlanActionKind.BLOCKED,
    PlanActionKind.INSUFFICIENT_EVIDENCE,
}
