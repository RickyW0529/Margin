"""Backtest script theme-toggle behavior tests.

Verifies that the theme-hotness factor can be isolated via the ``theme_enabled``
flag, ensuring candidates differ only when the additive theme factor is active.
"""

from __future__ import annotations

import pandas as pd

import scripts.backtest_three_quant_pools_db as backtest
from margin.valuation_discovery.quant.pool_defaults import QuantPoolStrategyPreset


def test_run_pool_backtest_can_disable_theme_hotness(monkeypatch) -> None:
    """Test that the theme toggle isolates the additive theme-hotness factor.

    Args:
        monkeypatch: Any: .

    Returns:
        None: .
    """
    rebalance_date = pd.Timestamp("2026-01-31")
    next_date = pd.Timestamp("2026-02-28")
    preset = QuantPoolStrategyPreset(
        universe_code="ALL_A",
        label="全A",
        benchmark_index_code=None,
        rebalance_frequency="monthly",
        buy_threshold=70.0,
        sell_threshold=50.0,
        min_avg_amount_20d=1.0,
        weighting="equal",
        factor_weights={
            "value": 0.0,
            "dividend": 0.0,
            "reversal": 0.0,
            "liquidity": 0.0,
            "volume_sentiment": 0.0,
            "momentum": 0.0,
            "risk_health": 0.0,
            "theme_hotness": 1.0,
        },
        candidate_policy={"manual_rebalance": {"min_holding_months": 0}},
        calibration={},
    )
    monkeypatch.setitem(backtest.DEFAULT_QUANT_POOL_PRESETS, "ALL_A", preset)
    prices = _prices(rebalance_date, next_date)
    daily_basic = pd.DataFrame(
        [
            _daily_basic("300308.SZ", rebalance_date),
            _daily_basic("plain.SZ", rebalance_date),
        ]
    )
    theme_signals = {
        rebalance_date: {
            "theme_hot_score": 80.0,
            "theme_signal_confirmed": True,
            "theme_relative_strength_20d": 0.15,
            "theme_relative_strength_60d": 0.25,
            "theme_amount_ratio_20d": 1.5,
            "theme_breadth_20d": 0.7,
            "theme_drawdown_60d": -0.05,
        }
    }

    enabled = backtest.run_pool_backtest(
        pool_code="ALL_A",
        cost_bps=100,
        rebalance_dates=[rebalance_date, next_date],
        prices=prices,
        daily_basic=daily_basic,
        company_pools={"snapshots": pd.DataFrame(), "members": {}},
        index_members={},
        security_names={"300308.SZ": "中际旭创", "plain.SZ": "普通公司"},
        theme_signals=theme_signals,
        theme_enabled=True,
    )
    disabled = backtest.run_pool_backtest(
        pool_code="ALL_A",
        cost_bps=100,
        rebalance_dates=[rebalance_date, next_date],
        prices=prices,
        daily_basic=daily_basic,
        company_pools={"snapshots": pd.DataFrame(), "members": {}},
        index_members={},
        security_names={"300308.SZ": "中际旭创", "plain.SZ": "普通公司"},
        theme_signals=theme_signals,
        theme_enabled=False,
    )

    enabled_candidates = enabled["latest_candidates"].query("manual_all_a_candidate")
    disabled_candidates = disabled["latest_candidates"].query("manual_all_a_candidate")
    assert set(enabled_candidates["security_id"]) == {"300308.SZ"}
    assert disabled_candidates.empty
    assert enabled["summary"]["theme_source"] == backtest.THEME_SOURCE
    assert disabled["summary"]["theme_source"] == "disabled"


def _prices(rebalance_date: pd.Timestamp, next_date: pd.Timestamp) -> dict[str, object]:
    """Build a deterministic price and feature panel fixture for two dates.

    Args:
        rebalance_date: pd.Timestamp: .
        next_date: pd.Timestamp: .

    Returns:
        dict[str, object]: .
    """
    securities = ["300308.SZ", "plain.SZ"]
    index = pd.DatetimeIndex([rebalance_date, next_date])
    feature_panel = pd.DataFrame(
        {
            "300308.SZ": [0.0, 0.0],
            "plain.SZ": [0.0, 0.0],
        },
        index=index,
    )
    return {
        "adj_close": pd.DataFrame({security: [10.0, 10.0] for security in securities}, index=index),
        "returns": pd.DataFrame({security: [0.0, 0.0] for security in securities}, index=index),
        "features": {
            "return_20d": feature_panel,
            "return_6m_ex_1m": feature_panel,
            "volatility_120d": feature_panel + 0.2,
            "max_drawdown_250d": feature_panel - 0.1,
            "avg_amount_20d": feature_panel + 100_000_000.0,
        },
    }


def _daily_basic(security_id: str, trade_date: pd.Timestamp) -> dict[str, object]:
    """Build a deterministic daily-basic row fixture for one security and date.

    Args:
        security_id: str: .
        trade_date: pd.Timestamp: .

    Returns:
        dict[str, object]: .
    """
    return {
        "security_id": security_id,
        "trade_date": trade_date,
        "pe_ttm": 10.0,
        "pb": 1.0,
        "ps": 1.0,
        "dividend_yield": 0.02,
        "market_cap": 10_000_000_000.0,
        "turnover_rate": 0.01,
    }
