"""News target selection from quant results.

The selector intentionally does not impose top-N or per-industry truncation.
Capacity and provider rate limits belong to the downstream orchestration layer;
this layer preserves coverage for every strategy-eligible quant result.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from margin.news.models import NewsTarget, TargetTriggerType
from margin.valuation_discovery.models import (
    QuantResult,
    ResearchGuardrail,
    ScreeningStatus,
)


class NewsTargetSelector:
    """Select company targets that should receive news refresh after quant."""

    def __init__(
        self,
        *,
        include_near_threshold: bool = True,
        allowed_guardrails: tuple[ResearchGuardrail, ...] = (
            ResearchGuardrail.RESEARCH_ALLOWED,
            ResearchGuardrail.LIMITED_RESEARCH,
            ResearchGuardrail.OVERHEAT_CAUTION,
            ResearchGuardrail.CONFIDENCE_REDUCED,
            ResearchGuardrail.THESIS_RECHECK_REQUIRED,
        ),
    ) -> None:
        """Initialize the selector with eligibility and guardrail filters.

        Args:
            include_near_threshold: Whether near-threshold results are eligible.
            allowed_guardrails: Guardrails that permit news refresh.
        """
        self._include_near_threshold = include_near_threshold
        self._allowed_guardrails = allowed_guardrails

    def select(
        self,
        *,
        scope_version_id: str,
        quant_run_id: str,
        results: Iterable[QuantResult],
        decision_at: datetime | None = None,
    ) -> tuple[NewsTarget, ...]:
        """Return every eligible news target sorted by priority descending.

        Args:
            scope_version_id: The frozen scope version.
            quant_run_id: The quant run that produced the results.
            results: Iterable of ``QuantResult`` objects.
            decision_at: Optional decision timestamp; defaults to result
                creation time.

        Returns:
            Tuple of ``NewsTarget`` objects sorted by priority descending.
        """
        targets = [
            self._target_for(
                scope_version_id=scope_version_id,
                quant_run_id=quant_run_id,
                result=result,
                decision_at=decision_at or result.created_at,
            )
            for result in results
            if self._is_eligible(result)
        ]
        return tuple(
            sorted(targets, key=lambda item: (-item.priority, item.security_id))
        )

    def _is_eligible(self, result: QuantResult) -> bool:
        """Return whether a quant result is eligible for news refresh."""
        if result.research_guardrail not in self._allowed_guardrails:
            return False
        if result.screening_status == ScreeningStatus.PASS:
            return True
        return (
            self._include_near_threshold
            and result.screening_status == ScreeningStatus.NEAR_THRESHOLD
        )

    def _target_for(
        self,
        *,
        scope_version_id: str,
        quant_run_id: str,
        result: QuantResult,
        decision_at: datetime,
    ) -> NewsTarget:
        """Build a ``NewsTarget`` from one eligible quant result."""
        priority, _, trigger_type = _priority_and_reasons(result)
        details = result.factor_details
        name = str(details.get("name") or result.security_id)
        return NewsTarget(
            quant_run_id=quant_run_id,
            scope_version_id=scope_version_id,
            security_id=result.security_id,
            symbol=str(details.get("symbol") or result.security_id),
            name=name,
            trigger_type=trigger_type,
            decision_at=decision_at,
            priority=priority,
            aliases=tuple(str(value) for value in details.get("aliases", ())),
            industry_terms=tuple(
                str(value)
                for value in details.get(
                    "industry_terms",
                    (details.get("industry_id"),),
                )
                if value
            ),
        )


def _priority_and_reasons(
    result: QuantResult,
) -> tuple[int, tuple[str, ...], TargetTriggerType]:
    """Compute priority, reasons, and trigger type from a quant result."""
    priority = 100 if result.screening_status == ScreeningStatus.PASS else 60
    reasons: list[str] = [f"quant_{result.screening_status.value}"]
    trigger_type = (
        TargetTriggerType.QUANT_PASS
        if result.screening_status == ScreeningStatus.PASS
        else TargetTriggerType.NEAR_THRESHOLD
    )
    details = result.factor_details
    if bool(details.get("new_pass")):
        priority += 10
        reasons.append("new_pass")
        trigger_type = TargetTriggerType.NEW_PASS
    if result.review_required or bool(details.get("review_due")):
        priority += 20
        reasons.append("review_due")
        trigger_type = TargetTriggerType.REVIEW_DUE
    if bool(details.get("material_filing")):
        priority += 30
        reasons.append("material_filing")
        trigger_type = TargetTriggerType.MATERIAL_FILING
    if (
        result.research_guardrail == ResearchGuardrail.THESIS_RECHECK_REQUIRED
        or bool(details.get("thesis_invalidation_risk"))
    ):
        priority += 40
        reasons.append("thesis_invalidation_risk")
        trigger_type = TargetTriggerType.THESIS_INVALIDATION_RISK
    return priority, tuple(reasons), trigger_type
