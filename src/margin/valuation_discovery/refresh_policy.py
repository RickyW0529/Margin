"""Refresh policy decisions for valuation discovery."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RefreshPolicyEvent:
    """Deterministic action flags emitted by refresh policy classification.."""

    security_id: str | None = None
    recalculate_discount: bool = False
    create_news_target: bool = False
    create_ai_refresh: bool = False
    defer_ai_review: bool = False
    stop_downstream: bool = False
    reasons: tuple[str, ...] = ()


class RefreshPolicy:
    """Classify changes and failures into downstream refresh actions.."""

    def classify_price_move(
        self,
        *,
        security_id: str,
        old_discount: float,
        new_discount: float,
        watch_band: tuple[float, float],
    ) -> RefreshPolicyEvent:
        """Classify valuation discount movement.

        Args:
            security_id: str: .
            old_discount: float: .
            new_discount: float: .
            watch_band: tuple[float, float]: .

        Returns:
            RefreshPolicyEvent: .
        """
        lower, upper = watch_band
        was_in_band = lower <= old_discount <= upper
        is_in_band = lower <= new_discount <= upper
        reasons = ["price_move"]
        create_news_target = is_in_band and not was_in_band
        if create_news_target:
            reasons.append("entered_watch_band")
        return RefreshPolicyEvent(
            security_id=security_id,
            recalculate_discount=True,
            create_news_target=create_news_target,
            create_ai_refresh=False,
            reasons=tuple(reasons),
        )

    def classify_step_failure(self, *, step: str) -> RefreshPolicyEvent:
        """Classify refresh step failures into safe downstream behavior.

        Args:
            step: str: .

        Returns:
            RefreshPolicyEvent: .
        """
        if step == "run_quant":
            return RefreshPolicyEvent(
                stop_downstream=True,
                reasons=("quant_failure",),
            )
        if step in {"acquire_news", "index_text", "build_evidence"}:
            return RefreshPolicyEvent(
                defer_ai_review=True,
                stop_downstream=False,
                reasons=(f"{step}_failure", "ai_review_deferred"),
            )
        return RefreshPolicyEvent(
            stop_downstream=True,
            reasons=(f"{step}_failure",),
        )
