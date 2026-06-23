"""Growth factor calculator."""

from __future__ import annotations

import pandas as pd

from margin.valuation_discovery.quant.normalization import FactorNormalizer


class GrowthFactorCalculator:
    """Calculate industry-relative, winsorized growth scores."""

    WEIGHTS = {
        "revenue_yoy": 0.25,
        "profit_yoy": 0.25,
        "revenue_cagr_3y": 0.20,
        "profit_cagr_3y": 0.15,
        "margin_trend": 0.10,
        "roe_trend": 0.05,
    }

    def __init__(self, normalizer: FactorNormalizer | None = None) -> None:
        """Initialize the calculator."""
        self._normalizer = normalizer or FactorNormalizer()

    def calculate(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Return a 0-100 score with available-field weight renormalization."""
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
                output_column=f"{column}_growth_score",
            )
            available[column] = weight
        total_weight = sum(available.values())
        if total_weight == 0:
            scored["growth_score"] = 0.0
            return scored
        result = 0.0
        for column, weight in available.items():
            result = result + scored[f"{column}_growth_score"] * (
                weight / total_weight
            )
        scored["growth_score"] = result.clip(0.0, 100.0)
        return scored
