"""QuantAgent strategy profiles.

QuantAgent owns the user-facing choice of which deterministic quant strategy is
requested by scheduled research. The scoring implementation stays in
``valuation_discovery.quant`` so lower data/quant layers do not depend on
Agent runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class QuantAgentStrategyProfile:
    """Stable strategy fingerprint emitted by QuantAgent scheduled runs.."""

    profile_id: str
    strategy_family: str
    strategy_version: str
    model_family: str
    candidate_universe: str
    score_name: str
    top_n: int
    score_temperature: float
    max_stock_exposure: float
    min_cash: float
    exposure_mode: str
    daily_stop_loss: float
    daily_drawdown_stop: float
    cash_annual: float
    required_feature_groups: tuple[str, ...]

    def to_metadata(self) -> dict[str, Any]:
        """Return JSON-safe metadata for Context Store and orchestration logs.

        Returns:
            dict[str, Any]: .
        """
        return {
            "profile_id": self.profile_id,
            "strategy_family": self.strategy_family,
            "strategy_version": self.strategy_version,
            "model_family": self.model_family,
            "candidate_universe": self.candidate_universe,
            "score_name": self.score_name,
            "thresholds": {
                "top_n": self.top_n,
                "score_temperature": self.score_temperature,
                "max_stock_exposure": self.max_stock_exposure,
                "min_cash": self.min_cash,
                "exposure_mode": self.exposure_mode,
                "daily_stop_loss": self.daily_stop_loss,
                "daily_drawdown_stop": self.daily_drawdown_stop,
                "cash_annual": self.cash_annual,
            },
            "required_feature_groups": list(self.required_feature_groups),
            "runtime_boundary": "provider_free_serving_no_training",
        }

    def to_quant_strategy_metadata(self) -> dict[str, Any]:
        """Return the shape consumed by QuantInputSnapshot metadata.

        Returns:
            dict[str, Any]: .
        """
        metadata = self.to_metadata()
        return {
            "quant_strategy_version_id": self.strategy_version,
            "strategy_family": self.strategy_family,
            "factor_weights": {},
            "thresholds": dict(metadata["thresholds"]),
            "calibration_report_id": self.profile_id,
            "profile": metadata,
        }


CURRENT_QUANT_AGENT_ML_PROFILE = QuantAgentStrategyProfile(
    profile_id="liquid-large-mid-lgbm-recent-trend80-ddstop-v1",
    strategy_family="ml_lgbm_lifecycle",
    strategy_version="ml-lifecycle-v1",
    model_family="lgbm_lifecycle",
    candidate_universe="all_industry_a_share",
    score_name="lgbm_recent_serving_proxy",
    top_n=40,
    score_temperature=0.20,
    max_stock_exposure=0.80,
    min_cash=0.20,
    exposure_mode="trend80",
    daily_stop_loss=0.0,
    daily_drawdown_stop=0.10,
    cash_annual=0.03,
    required_feature_groups=(
        "market_liquidity_momentum",
        "fundamental_quality_growth",
        "industry_lifecycle",
        "moneyflow_margin_confirmation",
        "forecast_express_growth",
        "execution_tradeability",
    ),
)


def current_quant_agent_strategy_profile() -> QuantAgentStrategyProfile:
    """Return the currently selected scheduled QuantAgent strategy profile.

    Returns:
        QuantAgentStrategyProfile: .
    """
    return CURRENT_QUANT_AGENT_ML_PROFILE
