"""Immutable state contract for the v0.2 AI delta review graph."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Self

from pydantic import BaseModel, Field, field_validator

from margin.news.models import ensure_utc


class ReviewMode(StrEnum):
    """Deterministic route selected before expensive graph work."""

    FULL_REVIEW = "full_review"
    DELTA_REVIEW = "delta_review"
    CARRY_FORWARD_FAST_PATH = "carry_forward_fast_path"
    REVIEW_DEFERRED = "review_deferred"
    ABSTAIN = "abstain"


class ReviewOutcome(StrEnum):
    """Terminal result of one current review run."""

    CARRY_FORWARD_VERIFIED = "carry_forward_verified"
    UPDATE_ASSESSMENT = "update_assessment"
    DOWNGRADE_CONFIDENCE = "downgrade_confidence"
    INVALIDATE = "invalidate"
    ABSTAIN = "abstain"
    REVIEW_DEFERRED = "review_deferred"


class AIDeltaGraphState(BaseModel):
    """Frozen state passed between controlled LangGraph nodes."""

    graph_run_id: str
    graph_version: str = "ai-delta-review-v0.2.0"
    context_snapshot_id: str
    context_input_hash: str
    scope_version_id: str
    security_id: str
    decision_at: datetime
    quant_input_snapshot_id: str | None = None
    current_quant_result_id: str | None = None
    previous_effective_assessment_id: str | None = None
    news_context_bundle_id: str | None = None
    context_quality: dict[str, Any] = Field(default_factory=dict)
    degradation_flags: tuple[str, ...] = Field(default_factory=tuple)
    change_set: dict[str, Any] = Field(default_factory=dict)
    review_mode: ReviewMode | None = None
    evidence_plan: dict[str, Any] = Field(default_factory=dict)
    evidence_package_ids: Annotated[
        tuple[str, ...],
        merge_unique_tuple,
    ] = Field(default_factory=tuple)
    evidence_gaps: Annotated[
        tuple[str, ...],
        merge_unique_tuple,
    ] = Field(default_factory=tuple)
    node_outputs: Annotated[
        dict[str, Any],
        merge_node_outputs,
    ] = Field(default_factory=dict)
    node_reflections: Annotated[
        tuple[dict[str, Any], ...],
        append_tuple,
    ] = Field(default_factory=tuple)
    tool_call_ids: Annotated[
        tuple[str, ...],
        merge_unique_tuple,
    ] = Field(default_factory=tuple)
    llm_call_ids: Annotated[
        tuple[str, ...],
        merge_unique_tuple,
    ] = Field(default_factory=tuple)
    errors: Annotated[
        tuple[str, ...],
        merge_unique_tuple,
    ] = Field(default_factory=tuple)
    draft_decision: dict[str, Any] = Field(default_factory=dict)
    citation_report: dict[str, Any] = Field(default_factory=dict)
    final_result: dict[str, Any] = Field(default_factory=dict)
    current_review_outcome: ReviewOutcome | None = None
    effective_assessment_id: str | None = None
    assessment_freshness: str | None = None
    stale_reason: str | None = None
    graph_step_count: Annotated[int, add_count] = 0
    llm_call_count: Annotated[int, add_count] = 0
    retrieval_count: Annotated[int, add_count] = 0
    repair_count: Annotated[int, add_count] = 0
    max_graph_steps: int = 24
    target_llm_calls: int = 8
    max_llm_calls: int = 16

    model_config = {"frozen": True}

    @field_validator("decision_at")
    @classmethod
    def normalize_decision_at(cls, value: datetime) -> datetime:
        """Normalize the immutable decision time to UTC."""
        return ensure_utc(value)

    @property
    def identity_hash(self) -> str:
        """Return a deterministic hash of graph identity fields."""
        payload = {
            field: (
                getattr(self, field).isoformat()
                if isinstance(getattr(self, field), datetime)
                else getattr(self, field)
            )
            for field in sorted(_IDENTITY_FIELDS)
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()

    def with_updates(self, **updates: Any) -> Self:
        """Return an updated state while rejecting identity mutation.

        Args:
            **updates: Field updates to apply to the frozen state.

        Returns:
            A new ``AIDeltaGraphState`` with the specified updates applied.

        Raises:
            ValueError: If unknown fields are supplied or immutable identity
                fields are changed.
        """
        unknown = set(updates) - set(type(self).model_fields)
        if unknown:
            raise ValueError(
                "unknown graph state fields: " + ",".join(sorted(unknown))
            )
        changed_identity = [
            field
            for field in _IDENTITY_FIELDS.intersection(updates)
            if updates[field] != getattr(self, field)
        ]
        if changed_identity:
            raise ValueError(
                "immutable identity fields cannot change: "
                + ",".join(sorted(changed_identity))
            )
        return self.model_copy(update=updates)


def merge_unique_tuple(left: tuple[Any, ...], right: tuple[Any, ...]) -> tuple[Any, ...]:
    """Append tuple values while preserving first-seen order."""
    return tuple(dict.fromkeys((*left, *right)))


def append_tuple(left: tuple[Any, ...], right: tuple[Any, ...]) -> tuple[Any, ...]:
    """Append tuple values without deduplicating structured records."""
    return (*left, *right)


def merge_node_outputs(
    left: dict[str, Any],
    right: dict[str, Any],
) -> dict[str, Any]:
    """Merge parallel node outputs and nested package maps."""
    merged = dict(left)
    for key, value in right.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = {**current, **value}
        else:
            merged[key] = value
    return merged


def add_count(left: int, right: int) -> int:
    """Add counter deltas emitted by graph nodes."""
    return left + right


_IDENTITY_FIELDS = frozenset(
    {
        "graph_run_id",
        "context_snapshot_id",
        "context_input_hash",
        "scope_version_id",
        "security_id",
        "decision_at",
    }
)


def create_initial_state(
    *,
    graph_run_id: str,
    context_snapshot_id: str,
    context_input_hash: str,
    scope_version_id: str,
    security_id: str,
    decision_at: datetime,
    quant_input_snapshot_id: str | None = None,
    current_quant_result_id: str | None = None,
    previous_effective_assessment_id: str | None = None,
    news_context_bundle_id: str | None = None,
) -> AIDeltaGraphState:
    """Create a validated initial graph state from frozen context references.

    Args:
        graph_run_id: Unique identifier for this graph run.
        context_snapshot_id: Frozen context snapshot identifier.
        context_input_hash: Hash of the context payload.
        scope_version_id: Strategy scope version identifier.
        security_id: Security under review.
        decision_at: Point-in-time decision timestamp.
        quant_input_snapshot_id: Optional quant input snapshot reference.
        current_quant_result_id: Optional current quant result reference.
        previous_effective_assessment_id: Optional prior effective assessment.
        news_context_bundle_id: Optional news context bundle reference.

    Returns:
        A validated ``AIDeltaGraphState`` ready for graph execution.
    """
    return AIDeltaGraphState(
        graph_run_id=graph_run_id,
        context_snapshot_id=context_snapshot_id,
        context_input_hash=context_input_hash,
        scope_version_id=scope_version_id,
        security_id=security_id,
        decision_at=decision_at,
        quant_input_snapshot_id=quant_input_snapshot_id,
        current_quant_result_id=current_quant_result_id,
        previous_effective_assessment_id=previous_effective_assessment_id,
        news_context_bundle_id=news_context_bundle_id,
    )
