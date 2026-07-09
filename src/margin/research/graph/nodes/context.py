"""Frozen-context precheck and deterministic ReviewMode selection."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, field_validator

from margin.news.models import ensure_utc
from margin.research.graph.state import AIDeltaGraphState, ReviewMode


class GraphContextSnapshot(BaseModel):
    """Minimal immutable routing view of a ResearchContextSnapshot.."""

    context_snapshot_id: str
    input_hash: str
    scope_version_id: str
    security_id: str
    decision_at: datetime
    quant_input_valid: bool
    pit_valid: bool
    news_target_complete: bool
    provider_budget_available: bool
    review_due: bool
    material_quant_change: bool
    material_valuation_change: bool
    material_news_change: bool
    assumption_change: bool
    ambiguous_change: bool

    model_config = {"frozen": True}

    @field_validator("decision_at")
    @classmethod
    def normalize_decision_at(cls, value: datetime) -> datetime:
        """Normalize the decision timestamp to UTC.

        Args:
            value: datetime: .

        Returns:
            datetime: .
        """
        return ensure_utc(value)


class ContextPrecheckNode:
    """Validate identity, PIT, quant input, news completion, and budget.."""

    def __init__(self, context: GraphContextSnapshot) -> None:
        """Initialize the precheck node.

        Args:
            context: GraphContextSnapshot: .

        Returns:
            None: .
        """
        self._context = context

    def run(self, state: AIDeltaGraphState) -> AIDeltaGraphState:
        """Return a state routed to ABSTAIN/DEFERRED or ready for change-set.

        Args:
            state: AIDeltaGraphState: .

        Returns:
            AIDeltaGraphState: .
        """
        identity_errors = _identity_errors(state, self._context)
        if identity_errors:
            return state.with_updates(
                review_mode=ReviewMode.ABSTAIN,
                effective_assessment_id=state.previous_effective_assessment_id,
                stale_reason="context_identity_mismatch",
                errors=state.errors + tuple(identity_errors),
                graph_step_count=state.graph_step_count + 1,
            )
        if not self._context.quant_input_valid or not self._context.pit_valid:
            return state.with_updates(
                review_mode=ReviewMode.ABSTAIN,
                effective_assessment_id=state.previous_effective_assessment_id,
                stale_reason="context_pit_invalid",
                degradation_flags=state.degradation_flags + ("context_pit_invalid",),
                graph_step_count=state.graph_step_count + 1,
            )
        if not self._context.news_target_complete:
            return state.with_updates(
                review_mode=ReviewMode.REVIEW_DEFERRED,
                effective_assessment_id=state.previous_effective_assessment_id,
                stale_reason="news_target_incomplete",
                graph_step_count=state.graph_step_count + 1,
            )
        if not self._context.provider_budget_available:
            return state.with_updates(
                review_mode=ReviewMode.REVIEW_DEFERRED,
                effective_assessment_id=state.previous_effective_assessment_id,
                stale_reason="provider_budget_unavailable",
                graph_step_count=state.graph_step_count + 1,
            )
        return state.with_updates(
            context_quality={
                "quant_input_valid": True,
                "pit_valid": True,
                "news_target_complete": True,
            },
            graph_step_count=state.graph_step_count + 1,
        )


class ChangeSetBuilderNode:
    """Build deterministic change flags and select FULL/DELTA/CARRY.."""

    def __init__(self, context: GraphContextSnapshot) -> None:
        """Initialize the change-set builder.

        Args:
            context: GraphContextSnapshot: .

        Returns:
            None: .
        """
        self._context = context

    def run(self, state: AIDeltaGraphState) -> AIDeltaGraphState:
        """Compare frozen references and assign ReviewMode when deterministic.

        Args:
            state: AIDeltaGraphState: .

        Returns:
            AIDeltaGraphState: .
        """
        if state.review_mode in {ReviewMode.ABSTAIN, ReviewMode.REVIEW_DEFERRED}:
            return state
        changes = {
            "review_due": self._context.review_due,
            "material_quant_change": self._context.material_quant_change,
            "material_valuation_change": self._context.material_valuation_change,
            "material_news_change": self._context.material_news_change,
            "assumption_change": self._context.assumption_change,
            "ambiguous_change": self._context.ambiguous_change,
        }
        if state.previous_effective_assessment_id is None or self._context.review_due:
            mode = ReviewMode.FULL_REVIEW
        elif any(
            (
                self._context.material_quant_change,
                self._context.material_valuation_change,
                self._context.material_news_change,
                self._context.assumption_change,
            )
        ):
            mode = ReviewMode.DELTA_REVIEW
        elif self._context.ambiguous_change:
            mode = None
        else:
            mode = ReviewMode.CARRY_FORWARD_FAST_PATH
        return state.with_updates(
            change_set=changes,
            review_mode=mode,
            effective_assessment_id=(
                state.previous_effective_assessment_id
                if mode == ReviewMode.CARRY_FORWARD_FAST_PATH
                else state.effective_assessment_id
            ),
            graph_step_count=state.graph_step_count + 1,
        )


class CarryForwardRuleNode:
    """Apply the verified zero-LLM carry-forward rule.."""

    def __init__(self, context: GraphContextSnapshot) -> None:
        """Initialize the carry-forward rule node.

        Args:
            context: GraphContextSnapshot: .

        Returns:
            None: .
        """
        self._context = context

    def run(self, state: AIDeltaGraphState) -> AIDeltaGraphState:
        """Route unchanged, complete context to the fast path.

        Args:
            state: AIDeltaGraphState: .

        Returns:
            AIDeltaGraphState: .
        """
        checked = ContextPrecheckNode(self._context).run(state)
        if checked.review_mode is not None:
            return checked
        return ChangeSetBuilderNode(self._context).run(checked)


def _identity_errors(
    state: AIDeltaGraphState,
    context: GraphContextSnapshot,
) -> list[str]:
    """Return field mismatch error codes between state and frozen context.

    Args:
        state: AIDeltaGraphState: .
        context: GraphContextSnapshot: .

    Returns:
        list[str]: .
    """
    checks = {
        "context_snapshot_id": (
            state.context_snapshot_id,
            context.context_snapshot_id,
        ),
        "context_input_hash": (state.context_input_hash, context.input_hash),
        "scope_version_id": (state.scope_version_id, context.scope_version_id),
        "security_id": (state.security_id, context.security_id),
        "decision_at": (state.decision_at, context.decision_at),
    }
    return [
        f"{field}_mismatch" for field, (expected, actual) in checks.items() if expected != actual
    ]
