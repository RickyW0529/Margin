"""Quality factor calculator."""

from __future__ import annotations

import pandas as pd

from margin.valuation_discovery.quant.normalization import FactorNormalizer


class QualityFactorCalculator:
    """Calculate quality factor scores from standardized quant columns."""

    WEIGHTS = {
        "roe_ttm": 0.20,
        "roic_ttm": 0.20,
        "gross_margin_ttm": 0.15,
        "net_margin_ttm": 0.10,
        "ocf_to_net_profit": 0.20,
        "liability_ratio": 0.10,
        "interest_coverage": 0.05,
    }

    DIRECTIONS = {
        "roe_ttm": "higher",
        "roic_ttm": "higher",
        "gross_margin_ttm": "higher",
        "net_margin_ttm": "higher",
        "ocf_to_net_profit": "higher",
        "liability_ratio": "lower",
        "interest_coverage": "higher",
    }

    def __init__(self, normalizer: FactorNormalizer | None = None) -> None:
        """init  ."""
        self._normalizer = normalizer or FactorNormalizer()

    def calculate(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Return frame with component scores and `quality_score`."""
        scored = frame.copy()
        available_weights: dict[str, float] = {}
        for column, weight in self.WEIGHTS.items():
            if column not in scored.columns:
                continue
            scored = self._normalizer.percentile_score(
                scored,
                column,
                direction=self.DIRECTIONS[column],
                output_column=f"{column}_quality_score",
            )
            available_weights[column] = weight
        total_weight = sum(available_weights.values())
        if total_weight == 0:
            scored["quality_score"] = 0.0
            return scored
        score = 0.0
        for column, weight in available_weights.items():
            score = score + scored[f"{column}_quality_score"] * (weight / total_weight)
        scored["quality_score"] = score.clip(0.0, 100.0)
        return scored
