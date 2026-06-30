"""Factor calculator tests.

This module validates that quality, growth, momentum, and risk factor
calculators produce bounded 0-100 scores and apply expected penalties.
"""

from __future__ import annotations

import pandas as pd

from margin.valuation_discovery.quant.factors.growth import GrowthFactorCalculator
from margin.valuation_discovery.quant.factors.momentum import (
    MomentumFactorCalculator,
)
from margin.valuation_discovery.quant.factors.quality import QualityFactorCalculator
from margin.valuation_discovery.quant.factors.risk import RiskFactorCalculator


def test_quality_calculator_outputs_0_to_100_score() -> None:
    """Verify the quality calculator outputs scores in the 0-100 range.

    A company with strong fundamentals should receive a high quality score
    while all scores remain within the valid bounds.

    Returns:
        None.
    """
    frame = pd.DataFrame(
        {
            "security_id": ["good", "weak"],
            "industry_id": ["consumer", "consumer"],
            "roe_ttm": [0.20, 0.05],
            "roic_ttm": [0.18, 0.04],
            "gross_margin_ttm": [0.50, 0.20],
            "net_margin_ttm": [0.20, 0.04],
            "ocf_to_net_profit": [1.20, 0.50],
            "liability_ratio": [0.30, 0.70],
            "interest_coverage": [12.0, 2.0],
        }
    )

    scored = QualityFactorCalculator().calculate(frame)

    assert scored.loc[scored.security_id == "good", "quality_score"].iloc[0] > 80.0
    assert scored["quality_score"].between(0, 100).all()


def test_growth_calculator_rewards_sustainable_growth() -> None:
    """Verify broad, persistent growth outranks weak or negative growth.

    Returns:
        None.
    """
    frame = pd.DataFrame(
        {
            "security_id": ["good", "weak"],
            "industry_id": ["software", "software"],
            "revenue_yoy": [0.30, -0.05],
            "profit_yoy": [0.25, -0.10],
            "revenue_cagr_3y": [0.20, 0.01],
            "profit_cagr_3y": [0.18, -0.02],
            "margin_trend": [0.03, -0.04],
            "roe_trend": [0.02, -0.03],
        }
    )

    scored = GrowthFactorCalculator().calculate(frame)

    assert scored.loc[scored.security_id == "good", "growth_score"].iloc[0] > 80
    assert scored["growth_score"].between(0, 100).all()


def test_momentum_calculator_applies_short_term_overheat_penalty() -> None:
    """Verify a 20-day surge is recorded and reduces otherwise strong momentum.

    Returns:
        None.
    """
    frame = pd.DataFrame(
        {
            "security_id": ["steady", "overheated", "weak"],
            "industry_id": ["industrial", "industrial", "industrial"],
            "return_6m_ex_1m": [0.20, 0.30, -0.10],
            "return_12m_ex_1m": [0.25, 0.40, -0.15],
            "industry_relative_momentum": [0.08, 0.15, -0.08],
            "index_relative_momentum": [0.10, 0.18, -0.10],
            "ma_trend": [1.0, 1.0, 0.0],
            "return_20d": [0.08, 0.40, -0.03],
        }
    )

    scored = MomentumFactorCalculator().calculate(frame)

    hot = scored.loc[scored.security_id == "overheated"].iloc[0]
    assert hot["short_term_overheat_penalty"] == 15.0
    assert bool(hot["block_chase"]) is True
    assert scored["momentum_score"].between(0, 100).all()


def test_risk_calculator_scores_healthier_balance_and_market_risk_higher() -> None:
    """Verify lower volatility, drawdown, and accounting risk produce a higher score.

    Returns:
        None.
    """
    frame = pd.DataFrame(
        {
            "security_id": ["healthy", "risky"],
            "industry_id": ["consumer", "consumer"],
            "volatility_120d": [0.15, 0.60],
            "max_drawdown_250d": [-0.10, -0.55],
            "avg_amount_20d": [500_000_000, 60_000_000],
            "receivable_risk": [0.01, 0.30],
            "inventory_risk": [0.01, 0.25],
            "goodwill_to_equity": [0.02, 0.60],
            "pledge_ratio": [0.0, 0.50],
        }
    )

    scored = RiskFactorCalculator().calculate(frame)

    assert scored.loc[scored.security_id == "healthy", "risk_score"].iloc[0] > 80
    assert scored["risk_score"].between(0, 100).all()
