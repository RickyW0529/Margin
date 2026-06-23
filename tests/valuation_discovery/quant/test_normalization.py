"""Factor normalization tests."""

from __future__ import annotations

import pandas as pd

from margin.valuation_discovery.quant.normalization import FactorNormalizer


def test_industry_percentile_direction_higher_is_better() -> None:
    """industry percentile direction higher is better."""
    frame = pd.DataFrame(
        {
            "security_id": ["a", "b", "c"],
            "industry_id": ["bank", "bank", "bank"],
            "roe_ttm": [0.05, 0.10, 0.20],
        }
    )

    scored = FactorNormalizer().percentile_score(frame, "roe_ttm", direction="higher")

    assert scored.loc[scored.security_id == "c", "roe_ttm_score"].iloc[0] == 100.0


def test_industry_percentile_direction_lower_is_better() -> None:
    """industry percentile direction lower is better."""
    frame = pd.DataFrame(
        {
            "security_id": ["a", "b", "c"],
            "industry_id": ["tech", "tech", "tech"],
            "pb": [1.0, 2.0, 3.0],
        }
    )

    scored = FactorNormalizer().percentile_score(frame, "pb", direction="lower")

    assert scored.loc[scored.security_id == "a", "pb_score"].iloc[0] == 100.0
