"""Decision, citation repair, effective assessment, and finalize nodes."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

from margin.research.graph.state import AIDeltaGraphState, ReviewOutcome


class DecisionDraft(BaseModel):
    """Structured candidate decision composed from joined analyses."""

    outcome: ReviewOutcome
    confidence: float = Field(ge=0.0, le=1.0)
    conclusion: str = ""
    valuation_view: str = "uncertain"
    evidence_ids: tuple[str, ...] = Field(default_factory=tuple)
    changed_assumptions: tuple[dict[str, Any], ...] = Field(default_factory=tuple)
    llm_call_ids: tuple[str, ...] = Field(default_factory=tuple)

    model_config = {"frozen": True}


class CitationReview(BaseModel):
    """Structured citation validation result used by the repair router."""

    valid: bool
    repairable: bool = False
    invalid_evidence_ids: tuple[str, ...] = Field(default_factory=tuple)
    reason: str | None = None

    model_config = {"frozen": True}


DecisionHandler = Callable[[AIDeltaGraphState], dict[str, Any]]
CitationValidationHandler = Callable[
    [dict[str, Any], AIDeltaGraphState],
    dict[str, Any],
]


class DeltaDecisionComposerNode:
    """Compose one structured delta decision after analysis joins."""

    def __init__(self, handler: DecisionHandler) -> None:
        """Initialize the node.

        Args:
            handler: Decision handler that composes the delta decision.
        """
        self._handler = handler

    def __call__(self, state: AIDeltaGraphState) -> dict[str, Any]:
        """Compose a structured delta decision from joined analysis outputs."""
        try:
            draft = DecisionDraft.model_validate(self._handler(state))
            if draft.outcome in {
                ReviewOutcome.CARRY_FORWARD_VERIFIED,
                ReviewOutcome.REVIEW_DEFERRED,
            }:
                raise ValueError("forbidden_outcome")
        except Exception as exc:  # noqa: BLE001 - raw external output is excluded
            reason = (
                "forbidden_outcome"
                if isinstance(exc, ValueError) and str(exc) == "forbidden_outcome"
                else type(exc).__name__
            )
            return {
                "draft_decision": {
                    "outcome": ReviewOutcome.ABSTAIN,
                    "confidence": 0.0,
                    "evidence_ids": (),
                    "changed_assumptions": (),
                },
                "errors": (f"delta_decision:{reason}",),
                "graph_step_count": 1,
            }
        payload = draft.model_dump(mode="python")
        return {
            "draft_decision": payload,
            "node_outputs": {"delta_decision": payload},
            "llm_call_ids": draft.llm_call_ids,
            "llm_call_count": len(draft.llm_call_ids),
            "graph_step_count": 1,
        }


class CitationValidationNode:
    """Validate only references already present in the draft decision."""

    def __init__(self, validator: CitationValidationHandler) -> None:
        """Initialize the node.

        Args:
            validator: Citation validation handler to invoke.
        """
        self._validator = validator

    def __call__(self, state: AIDeltaGraphState) -> dict[str, Any]:
        """Validate citation references and return a structured report."""
        try:
            report = CitationReview.model_validate(
                self._validator(state.draft_decision, state)
            )
        except Exception as exc:  # noqa: BLE001 - validator details stay internal
            report = CitationReview(
                valid=False,
                repairable=False,
                reason=f"validator_{type(exc).__name__}",
            )
        payload = report.model_dump(mode="python")
        return {
            "citation_report": payload,
            "node_outputs": {"citation_validation": payload},
            "graph_step_count": 1,
        }


class RepairDecisionNode:
    """Remove invalid references once; never add facts or evidence IDs."""

    def __call__(self, state: AIDeltaGraphState) -> dict[str, Any]:
        """Remove invalid evidence references once without adding new facts."""
        report = CitationReview.model_validate(state.citation_report)
        draft = DecisionDraft.model_validate(state.draft_decision)
        base_update: dict[str, Any] = {
            "repair_count": 1,
            "graph_step_count": 1,
        }
        if not report.repairable:
            return {
                **base_update,
                "current_review_outcome": ReviewOutcome.ABSTAIN,
                "effective_assessment_id": state.previous_effective_assessment_id,
                "assessment_freshness": "stale",
                "stale_reason": "citation_validation_failed",
                "node_outputs": {
                    "repair_decision": {
                        "repaired": False,
                        "reason": report.reason or "unrepairable",
                    }
                },
            }
        invalid_ids = set(report.invalid_evidence_ids)
        repaired_ids = tuple(
            evidence_id
            for evidence_id in draft.evidence_ids
            if evidence_id not in invalid_ids
        )
        if not repaired_ids:
            return {
                **base_update,
                "current_review_outcome": ReviewOutcome.ABSTAIN,
                "effective_assessment_id": state.previous_effective_assessment_id,
                "assessment_freshness": "stale",
                "stale_reason": "citation_validation_failed",
                "node_outputs": {
                    "repair_decision": {
                        "repaired": False,
                        "reason": "no_valid_evidence_remaining",
                    }
                },
            }
        repaired = draft.model_copy(update={"evidence_ids": repaired_ids})
        return {
            **base_update,
            "draft_decision": repaired.model_dump(mode="python"),
            "citation_report": {},
            "node_outputs": {
                "repair_decision": {
                    "repaired": True,
                    "removed_evidence_ids": tuple(report.invalid_evidence_ids),
                }
            },
        }


class CarryForwardDecisionNode:
    """Produce verified carry-forward without an LLM call."""

    def __call__(self, state: AIDeltaGraphState) -> dict[str, Any]:
        """Produce a verified carry-forward outcome without an LLM call."""
        return {
            "current_review_outcome": ReviewOutcome.CARRY_FORWARD_VERIFIED,
            "effective_assessment_id": state.previous_effective_assessment_id,
            "assessment_freshness": "verified_current",
            "stale_reason": None,
            "graph_step_count": 1,
        }


class ReviewDeferredNode:
    """Preserve the previous effective assessment during temporary deferral."""

    def __call__(self, state: AIDeltaGraphState) -> dict[str, Any]:
        """Preserve the previous assessment during a temporary deferral."""
        return {
            "current_review_outcome": ReviewOutcome.REVIEW_DEFERRED,
            "effective_assessment_id": state.previous_effective_assessment_id,
            "assessment_freshness": "stale",
            "stale_reason": state.stale_reason or "review_deferred",
            "graph_step_count": 1,
        }


class AbstainNode:
    """Preserve the previous effective assessment when this review abstains."""

    def __call__(self, state: AIDeltaGraphState) -> dict[str, Any]:
        """Preserve the previous assessment when this review abstains."""
        return {
            "current_review_outcome": ReviewOutcome.ABSTAIN,
            "effective_assessment_id": state.previous_effective_assessment_id,
            "assessment_freshness": "stale",
            "stale_reason": state.stale_reason or "review_abstained",
            "graph_step_count": 1,
        }


class FinalizeNode:
    """Apply effective-assessment semantics and emit a terminal result."""

    def __call__(self, state: AIDeltaGraphState) -> dict[str, Any]:
        """Apply effective-assessment semantics and emit a terminal result."""
        outcome = state.current_review_outcome or _draft_outcome(state)
        effective_assessment_id = state.effective_assessment_id
        freshness = state.assessment_freshness
        stale_reason = state.stale_reason

        if outcome in {
            ReviewOutcome.UPDATE_ASSESSMENT,
            ReviewOutcome.DOWNGRADE_CONFIDENCE,
            ReviewOutcome.INVALIDATE,
        }:
            effective_assessment_id = _assessment_id(state, outcome)
            freshness = "current"
            stale_reason = None
        elif outcome == ReviewOutcome.CARRY_FORWARD_VERIFIED:
            effective_assessment_id = state.previous_effective_assessment_id
            freshness = "verified_current"
            stale_reason = None
        elif outcome in {ReviewOutcome.ABSTAIN, ReviewOutcome.REVIEW_DEFERRED}:
            effective_assessment_id = state.previous_effective_assessment_id
            freshness = freshness or "stale"

        result = {
            "graph_run_id": state.graph_run_id,
            "context_snapshot_id": state.context_snapshot_id,
            "current_review_outcome": outcome,
            "effective_assessment_id": effective_assessment_id,
            "assessment_freshness": freshness,
            "stale_reason": stale_reason,
            "evidence_ids": tuple(state.draft_decision.get("evidence_ids", ())),
            "confidence": float(state.draft_decision.get("confidence", 0.0)),
            "conclusion": str(state.draft_decision.get("conclusion", "")),
            "valuation_view": str(
                state.draft_decision.get("valuation_view", "uncertain")
            ),
            "changed_assumptions": tuple(
                state.draft_decision.get("changed_assumptions", ())
            ),
            "llm_call_count": state.llm_call_count,
            "tool_call_count": len(state.tool_call_ids),
        }
        return {
            "current_review_outcome": outcome,
            "effective_assessment_id": effective_assessment_id,
            "assessment_freshness": freshness,
            "stale_reason": stale_reason,
            "final_result": result,
            "node_outputs": {"finalize": result},
            "graph_step_count": 1,
        }


def _draft_outcome(state: AIDeltaGraphState) -> ReviewOutcome:
    """Coerce the draft decision outcome into a ReviewOutcome enum member."""
    value = state.draft_decision.get("outcome", ReviewOutcome.ABSTAIN)
    return value if isinstance(value, ReviewOutcome) else ReviewOutcome(value)


def _assessment_id(
    state: AIDeltaGraphState,
    outcome: ReviewOutcome,
) -> str:
    """Derive a deterministic effective assessment ID from the graph run."""
    payload = {
        "graph_run_id": state.graph_run_id,
        "outcome": outcome.value,
        "draft_decision": state.draft_decision,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    ).encode("utf-8")
    return "assess_" + hashlib.sha256(encoded).hexdigest()[:24]
