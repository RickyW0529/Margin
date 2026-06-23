"""Factor normalization utilities."""

from __future__ import annotations

import pandas as pd


class FactorNormalizer:
    """Winsorize and percentile-normalize factor columns by industry."""

    def __init__(self, lower_quantile: float = 0.01, upper_quantile: float = 0.99) -> None:
        """init  ."""
        self._lower_quantile = lower_quantile
        self._upper_quantile = upper_quantile

    def percentile_score(
        self,
        frame: pd.DataFrame,
        column: str,
        *,
        direction: str,
        industry_column: str = "industry_id",
        output_column: str | None = None,
    ) -> pd.DataFrame:
        """Return a copy with a 0-100 industry percentile score column."""
        if direction not in {"higher", "lower"}:
            raise ValueError("direction must be 'higher' or 'lower'")
        scored = frame.copy()
        output = output_column or f"{column}_score"
        values = pd.to_numeric(scored[column], errors="coerce")
        lower = values.quantile(self._lower_quantile)
        upper = values.quantile(self._upper_quantile)
        scored[f"__{column}_winsorized"] = values.clip(lower=lower, upper=upper)
        pct = scored.groupby(industry_column)[f"__{column}_winsorized"].rank(
            method="max",
            pct=True,
            ascending=direction == "higher",
        )
        scored[output] = (pct * 100).fillna(0.0).clip(0.0, 100.0)
        return scored.drop(columns=[f"__{column}_winsorized"])
