"""Momentum factor calculator."""

from __future__ import annotations

import pandas as pd

from margin.valuation_discovery.quant.normalization import FactorNormalizer


class MomentumFactorCalculator:
    """Calculate medium-term relative momentum with explicit overheat penalties."""

    WEIGHTS = {
        "return_6m_ex_1m": 0.30,
        "return_12m_ex_1m": 0.25,
        "industry_relative_momentum": 0.20,
        "index_relative_momentum": 0.15,
        "ma_trend": 0.10,
    }

    def __init__(self, normalizer: FactorNormalizer | None = None) -> None:
        """Initialize the calculator."""
        self._normalizer = normalizer or FactorNormalizer()

    def calculate(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Return momentum scores and structured short-term heat controls."""
        scored = frame.copy()
        if "industry_id" not in scored.columns:
            scored["industry_id"] = "__all__"
        available: dict[str, float] = {}
        for column, weight in self.WEIGHTS.items():
            if column not in scored.columns:
                continue
            scored = self._normalizer.percentile_score(
                scored,
                column,
                direction="higher",
                output_column=f"{column}_momentum_score",
            )
            available[column] = weight
        total_weight = sum(available.values())
        if total_weight == 0:
            scored["momentum_score"] = 0.0
        else:
            result = 0.0
            for column, weight in available.items():
                result = result + scored[f"{column}_momentum_score"] * (
                    weight / total_weight
                )
            scored["momentum_score"] = result

        return_20d = pd.to_numeric(
            scored.get("return_20d", pd.Series(0.0, index=scored.index)),
            errors="coerce",
        ).fillna(0.0)
        scored["short_term_overheat_penalty"] = 0.0
        scored.loc[return_20d > 0.25, "short_term_overheat_penalty"] = 5.0
        scored.loc[return_20d > 0.30, "short_term_overheat_penalty"] = 10.0
        scored.loc[return_20d > 0.35, "short_term_overheat_penalty"] = 15.0
        scored["block_chase"] = return_20d > 0.35
        scored["momentum_score"] = (
            scored["momentum_score"] - scored["short_term_overheat_penalty"]
        ).clip(0.0, 100.0)
        return scored
