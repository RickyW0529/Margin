"""Default manual-rebalance quant presets for supported A-share pools."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class QuantPoolStrategyPreset:
    """One user-facing monthly rebalance strategy preset."""

    universe_code: str
    label: str
    benchmark_index_code: str | None
    rebalance_frequency: str
    buy_threshold: float
    sell_threshold: float
    min_avg_amount_20d: float
    weighting: str
    factor_weights: dict[str, float]
    candidate_policy: dict[str, Any]
    calibration: dict[str, Any]

    def as_payload(self) -> dict[str, Any]:
        """Return a JSON-serializable preset payload."""
        payload = asdict(self)
        payload["factor_weights"] = _normalized_weights(self.factor_weights)
        return payload


CSI300_WEIGHTS: dict[str, float] = {
    "value": 0.306,
    "dividend": 0.144,
    "reversal": 0.090,
    "liquidity": 0.090,
    "volume_sentiment": 0.054,
    "momentum": 0.126,
    "risk_health": 0.090,
    "theme_hotness": 0.100,
}

ALL_A_WEIGHTS: dict[str, float] = {
    "value": 0.324,
    "dividend": 0.144,
    "reversal": 0.108,
    "liquidity": 0.126,
    "volume_sentiment": 0.054,
    "momentum": 0.054,
    "risk_health": 0.090,
    "theme_hotness": 0.100,
}

CSI500_WEIGHTS: dict[str, float] = {
    "value": 0.342,
    "dividend": 0.144,
    "reversal": 0.126,
    "liquidity": 0.090,
    "volume_sentiment": 0.054,
    "momentum": 0.072,
    "risk_health": 0.072,
    "theme_hotness": 0.100,
}

THEME_TILT_POLICY: dict[str, Any] = {
    "enabled": True,
    "default_theme": "optical_module_cpo",
    "theme_weight": 0.10,
    "entry_score": 70.0,
    "entry_confirmation_months": 2,
    "exit_score": 55.0,
    "exit_confirmation_months": 2,
    "max_new_names_per_theme": 5,
    "fallback_source": "curated_seed_when_concept_api_unavailable",
}

MANUAL_REBALANCE_POLICY: dict[str, Any] = {
    "min_holding_months": 2,
    "rebalance_buffer": "buy_threshold_above_sell_threshold",
}

DEFAULT_QUANT_POOL_PRESETS: dict[str, QuantPoolStrategyPreset] = {
    "CSI300": QuantPoolStrategyPreset(
        universe_code="CSI300",
        label="沪深300",
        benchmark_index_code="000300.SH",
        rebalance_frequency="monthly",
        buy_threshold=60.0,
        sell_threshold=40.0,
        min_avg_amount_20d=200_000_000.0,
        weighting="equal",
        factor_weights=CSI300_WEIGHTS,
        candidate_policy={
            "no_top_n": True,
            "market_cap_filter": False,
            "manual_rebalance": MANUAL_REBALANCE_POLICY,
            "second_stage": "ai_research_reduces_company_count_and_allocation",
            "theme_tilt": THEME_TILT_POLICY,
        },
        calibration={
            "cost_bps": 100,
            "annual_return": 0.1421,
            "max_drawdown": -0.1057,
            "information_ratio": 0.8525,
            "avg_holdings": 86.9,
            "source": "db_backtest_theme_tilt_20240624_20260623",
        },
    ),
    "ALL_A": QuantPoolStrategyPreset(
        universe_code="ALL_A",
        label="全A",
        benchmark_index_code=None,
        rebalance_frequency="monthly",
        buy_threshold=76.0,
        sell_threshold=52.0,
        min_avg_amount_20d=100_000_000.0,
        weighting="equal",
        factor_weights=ALL_A_WEIGHTS,
        candidate_policy={
            "no_top_n": True,
            "market_cap_filter": False,
            "manual_rebalance": MANUAL_REBALANCE_POLICY,
            "second_stage": "ai_research_reduces_company_count_and_allocation",
            "theme_tilt": THEME_TILT_POLICY,
        },
        calibration={
            "cost_bps": 100,
            "annual_return": 0.1558,
            "max_drawdown": -0.1413,
            "information_ratio": 0.8883,
            "avg_holdings": 125.5,
            "source": "db_backtest_theme_tilt_20240624_20260623",
        },
    ),
    "CSI500": QuantPoolStrategyPreset(
        universe_code="CSI500",
        label="中证500",
        benchmark_index_code="000905.SH",
        rebalance_frequency="monthly",
        buy_threshold=64.0,
        sell_threshold=40.0,
        min_avg_amount_20d=200_000_000.0,
        weighting="equal",
        factor_weights=CSI500_WEIGHTS,
        candidate_policy={
            "no_top_n": True,
            "market_cap_filter": False,
            "manual_rebalance": MANUAL_REBALANCE_POLICY,
            "second_stage": "ai_research_reduces_company_count_and_allocation",
            "theme_tilt": THEME_TILT_POLICY,
        },
        calibration={
            "cost_bps": 100,
            "annual_return": 0.2556,
            "max_drawdown": -0.1478,
            "information_ratio": 1.2647,
            "avg_holdings": 87.5,
            "source": "db_backtest_theme_tilt_20240624_20260623",
        },
    ),
}


def quant_strategy_defaults_payload() -> dict[str, Any]:
    """Return the current default strategy payload for API/bootstrap use."""
    return {
        "profile": "monthly_manual_pool_threshold_no_top_n_v1",
        "default_universe": "ALL_A",
        "execution_boundary": "research_only_no_order",
        "presets": {
            code: preset.as_payload()
            for code, preset in DEFAULT_QUANT_POOL_PRESETS.items()
        },
    }


def default_quant_strategy_thresholds() -> dict[str, Any]:
    """Return thresholds for the built-in ``QuantStrategyVersion``."""
    payload = quant_strategy_defaults_payload()
    return {
        "profile": payload["profile"],
        "default_universe": payload["default_universe"],
        "execution_boundary": payload["execution_boundary"],
        "presets": payload["presets"],
    }


def default_factor_weights(universe_code: str = "ALL_A") -> dict[str, float]:
    """Return normalized factor weights for a supported universe."""
    preset = DEFAULT_QUANT_POOL_PRESETS.get(universe_code, DEFAULT_QUANT_POOL_PRESETS["ALL_A"])
    return _normalized_weights(preset.factor_weights)


def _normalized_weights(weights: dict[str, float]) -> dict[str, float]:
    """Return weights normalized to sum to 1.0, falling back to the input."""
    total = sum(value for value in weights.values() if value > 0)
    if total <= 0:
        return dict(weights)
    return {key: value / total for key, value in weights.items()}
