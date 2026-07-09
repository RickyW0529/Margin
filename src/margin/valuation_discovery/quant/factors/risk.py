"""Risk-health factor calculator."""

from __future__ import annotations

import pandas as pd

from margin.valuation_discovery.quant.normalization import FactorNormalizer


class RiskFactorCalculator:
    """Calculate risk-health scores where higher means lower risk.."""

    WEIGHTS = {
        "volatility_120d": 0.20,
        "max_drawdown_250d": 0.20,
        "avg_amount_20d": 0.15,
        "receivable_risk": 0.15,
        "inventory_risk": 0.10,
        "goodwill_to_equity": 0.10,
        "pledge_ratio": 0.10,
    }
    DIRECTIONS = {
        "volatility_120d": "lower",
        "max_drawdown_250d": "higher",
        "avg_amount_20d": "higher",
        "receivable_risk": "lower",
        "inventory_risk": "lower",
        "goodwill_to_equity": "lower",
        "pledge_ratio": "lower",
    }

    def __init__(self, normalizer: FactorNormalizer | None = None) -> None:
        """Initialize the calculator.

        Args:
            normalizer: FactorNormalizer | None: .

        Returns:
            None: .
        """
        self._normalizer = normalizer or FactorNormalizer()

    def calculate(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Return a 0-100 health score using available risk dimensions.

        Args:
            frame: pd.DataFrame: .

        Returns:
            pd.DataFrame: .
        """
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
                direction=self.DIRECTIONS[column],
                output_column=f"{column}_risk_score",
            )
            available[column] = weight
        total_weight = sum(available.values())
        if total_weight == 0:
            scored["risk_score"] = 0.0
            return scored
        result = 0.0
        for column, weight in available.items():
            result = result + scored[f"{column}_risk_score"] * (weight / total_weight)
        scored["risk_score"] = result.clip(0.0, 100.0)
        return scored
