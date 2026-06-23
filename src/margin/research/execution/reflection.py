"""Bounded reflection models and evidence-integrity checks."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class ReflectionAction(StrEnum):
    """Only actions a critic may return."""

    ACCEPT = "accept"
    REVISE = "revise"
    NEEDS_EVIDENCE = "needs_evidence"
    ABSTAIN = "abstain"


class NodeReflection(BaseModel):
    """Structured critic output; it never mutates graph state directly."""

    action: ReflectionAction
    reasons: tuple[str, ...] = Field(default_factory=tuple)
    evidence_ids: tuple[str, ...] = Field(default_factory=tuple)

    model_config = {"frozen": True}

    def preserves_evidence(self, existing_evidence_ids: set[str]) -> bool:
        """Return whether critic references only existing evidence IDs."""
        return set(self.evidence_ids) <= existing_evidence_ids


REFLECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": [action.value for action in ReflectionAction],
        },
        "reasons": {"type": "array", "items": {"type": "string"}},
        "evidence_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["action"],
}
