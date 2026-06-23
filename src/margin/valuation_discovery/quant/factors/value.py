"""Value factor calculator."""

from __future__ import annotations

import pandas as pd

from margin.valuation_discovery.quant.scoring import FactorScorer


class ValueFactorCalculator:
    """Calculate valuation factor scores."""

    def __init__(self, scorer: FactorScorer | None = None) -> None:
        """init  ."""
        self._scorer = scorer or FactorScorer()

    def calculate(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Return frame with value component scores."""
        return self._scorer.score_value(frame)
