"""Factor scoring and score combination."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from margin.valuation_discovery.models import DataStatus, ResearchGuardrail, ScreeningStatus
from margin.valuation_discovery.quant.normalization import FactorNormalizer


@dataclass(frozen=True)
class FactorGroupScores:
    """Input group scores for final score composition."""

    security_id: str
    quality_score: float
    value_score: float
    growth_score: float
    momentum_score: float
    risk_score: float


@dataclass(frozen=True)
class CombinedFactorScore(FactorGroupScores):
    """Combined score with final weighted score."""

    final_score: float


@dataclass(frozen=True)
class QuantStatusDecision:
    """Orthogonal screening status and guardrail decision."""

    screening_status: ScreeningStatus
    research_guardrail: ResearchGuardrail
    review_required: bool = False
    review_reasons: tuple[str, ...] = ()


class FactorScorer:
    """Score value factors and combine factor groups."""

    GROUP_WEIGHTS = {
        "quality_score": 0.35,
        "value_score": 0.25,
        "growth_score": 0.15,
        "momentum_score": 0.15,
        "risk_score": 0.10,
    }

    def __init__(self, normalizer: FactorNormalizer | None = None) -> None:
        """Initialize the scorer with an optional custom normalizer."""
        self._normalizer = normalizer or FactorNormalizer()

    def score_value(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Score valuation factors, treating negative PE as invalid."""
        scored = frame.copy()
        valid_pe = pd.to_numeric(scored["pe_ttm"], errors="coerce")
        scored["__pe_for_rank"] = valid_pe.where(valid_pe > 0)
        scored = self._normalizer.percentile_score(
            scored,
            "__pe_for_rank",
            direction="lower",
            output_column="pe_score",
        )
        scored.loc[valid_pe <= 0, "pe_score"] = 0.0
        if "pb" in scored.columns:
            scored = self._normalizer.percentile_score(
                scored,
                "pb",
                direction="lower",
                output_column="pb_score",
            )
        else:
            scored["pb_score"] = 0.0
        if "fcf_yield" in scored.columns:
            scored = self._normalizer.percentile_score(
                scored,
                "fcf_yield",
                direction="higher",
                output_column="fcf_yield_score",
            )
        else:
            scored["fcf_yield_score"] = 0.0
        scored["value_score"] = (
            0.45 * scored["pe_score"]
            + 0.25 * scored["pb_score"]
            + 0.30 * scored["fcf_yield_score"]
        ).clip(0.0, 100.0)
        return scored.drop(columns=["__pe_for_rank"])

    def combine(self, scores: FactorGroupScores) -> CombinedFactorScore:
        """Combine group scores using configured v0.2 weights."""
        final_score = (
            self.GROUP_WEIGHTS["quality_score"] * scores.quality_score
            + self.GROUP_WEIGHTS["value_score"] * scores.value_score
            + self.GROUP_WEIGHTS["growth_score"] * scores.growth_score
            + self.GROUP_WEIGHTS["momentum_score"] * scores.momentum_score
            + self.GROUP_WEIGHTS["risk_score"] * scores.risk_score
        )
        return CombinedFactorScore(
            security_id=scores.security_id,
            quality_score=scores.quality_score,
            value_score=scores.value_score,
            growth_score=scores.growth_score,
            momentum_score=scores.momentum_score,
            risk_score=scores.risk_score,
            final_score=final_score,
        )

    def determine_status(
        self,
        scores: CombinedFactorScore,
        *,
        data_status: DataStatus,
        risk_flags: tuple[str, ...],
        short_term_overheat: bool,
    ) -> QuantStatusDecision:
        """Determine screening status and research guardrail from factor scores."""
        if data_status != DataStatus.OK:
            return QuantStatusDecision(
                screening_status=ScreeningStatus.REJECT,
                research_guardrail=ResearchGuardrail.RESEARCH_BLOCKED,
                review_required=True,
                review_reasons=("data_status_not_ok",),
            )
        if scores.risk_score < 40 or risk_flags:
            return QuantStatusDecision(
                screening_status=ScreeningStatus.REJECT,
                research_guardrail=ResearchGuardrail.THESIS_RECHECK_REQUIRED,
                review_required=True,
                review_reasons=tuple(risk_flags) or ("risk_score_below_40",),
            )
        if scores.quality_score < 50:
            return QuantStatusDecision(
                screening_status=ScreeningStatus.WATCHLIST
                if scores.final_score >= 60
                else ScreeningStatus.REJECT,
                research_guardrail=ResearchGuardrail.CONFIDENCE_REDUCED,
                review_required=True,
                review_reasons=("quality_score_below_50",),
            )
        guardrail = (
            ResearchGuardrail.OVERHEAT_CAUTION
            if short_term_overheat
            else ResearchGuardrail.RESEARCH_ALLOWED
        )
        if (
            scores.final_score >= 80
            and scores.quality_score >= 60
            and scores.risk_score >= 50
        ):
            return QuantStatusDecision(
                screening_status=ScreeningStatus.PASS,
                research_guardrail=guardrail,
            )
        if scores.final_score >= 70:
            return QuantStatusDecision(
                screening_status=ScreeningStatus.NEAR_THRESHOLD,
                research_guardrail=ResearchGuardrail.LIMITED_RESEARCH,
            )
        if scores.final_score >= 60:
            return QuantStatusDecision(
                screening_status=ScreeningStatus.WATCHLIST,
                research_guardrail=ResearchGuardrail.RESEARCH_ALLOWED,
            )
        return QuantStatusDecision(
            screening_status=ScreeningStatus.REJECT,
            research_guardrail=ResearchGuardrail.RESEARCH_BLOCKED,
        )
