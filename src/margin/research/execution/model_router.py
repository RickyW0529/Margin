"""Task-to-model routing helpers for v0.2 graph nodes."""

from __future__ import annotations

from margin.research.llm import ModelRouter, TaskType

NODE_TASK_TYPES: dict[str, TaskType] = {
    "evidence_plan": TaskType.EVIDENCE,
    "fundamental_analysis": TaskType.EVIDENCE,
    "valuation_analysis": TaskType.VALUATION,
    "risk_review": TaskType.RISK,
    "counter_argument": TaskType.REFLECT,
    "delta_decision": TaskType.SIGNAL,
    "citation_validation": TaskType.VALIDATION,
}


def task_type_for_node(node_name: str) -> TaskType:
    """Return the deterministic task route for a graph node."""
    return NODE_TASK_TYPES.get(node_name, TaskType.EVIDENCE)


__all__ = ["ModelRouter", "NODE_TASK_TYPES", "task_type_for_node"]
