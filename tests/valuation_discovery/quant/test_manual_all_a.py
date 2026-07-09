"""Manual All-A quant scoring tests.

This module validates that the manual All-A scoring strategy does not filter
by market cap, exposes explainable AI quant profiles without trade instructions,
and applies confidence-weighted theme hotness scoring.
"""

from __future__ import annotations

import pandas as pd

from margin.valuation_discovery.quant.manual_all_a import (
    DEFAULT_WEIGHTS,
    ManualAllAConfig,
    build_ai_quant_profile,
    score_manual_all_a,
    select_ai_quant_candidates,
)


def test_manual_all_a_scoring_does_not_filter_by_market_cap() -> None:
    """Verify manual All-A scoring keeps small companies when quality fields pass.

    Returns:
        None: .
    """
    frame = pd.DataFrame(
        [
            _row("small", market_cap=5_000_000_000.0, pe_ttm=8.0),
            _row("large", market_cap=500_000_000_000.0, pe_ttm=12.0),
        ]
    )

    scored = score_manual_all_a(
        frame,
        config=ManualAllAConfig(score_threshold=0.0),
    )
    candidates = select_ai_quant_candidates(
        scored,
        config=ManualAllAConfig(score_threshold=0.0),
    )

    assert set(candidates["security_id"]) == {"small", "large"}
    assert scored.loc[scored.security_id == "small", "manual_all_a_candidate"].iloc[0]
    assert scored.loc[scored.security_id == "large", "manual_all_a_candidate"].iloc[0]


def test_ai_quant_profile_exposes_key_fields_without_trade_instruction() -> None:
    """Verify the AI profile contains explainable quant facts, not direct order advice.

    Returns:
        None: .
    """
    scored = score_manual_all_a(
        pd.DataFrame([_row("000001.SZ", market_cap=120_000_000_000.0)]),
        config=ManualAllAConfig(score_threshold=0.0),
    )

    profile = build_ai_quant_profile(scored.iloc[0])

    assert profile["strategy_profile"] == "manual_all_a_no_market_cap_no_top_n"
    assert "manual_all_a_score" in profile["scores"]
    assert profile["raw_factors"]["market_cap"] == 120_000_000_000.0
    assert profile["execution_boundary"] == "research_only_no_order"
    assert "BUY" not in str(profile)
    assert "SELL" not in str(profile)


def test_theme_hotness_score_requires_confirmed_member_confidence() -> None:
    """Verify theme score is confidence-weighted and ignored until trend is confirmed.
    Returns:.

    Returns:
        None: .
    """
    zero_base_weights = {key: 0.0 for key in DEFAULT_WEIGHTS}
    frame = pd.DataFrame(
        [
            _row(
                "core",
                market_cap=10_000_000_000.0,
                theme_hot_score=80.0,
                theme_member_confidence=1.0,
                theme_signal_confirmed=True,
            ),
            _row(
                "weak",
                market_cap=10_000_000_000.0,
                theme_hot_score=80.0,
                theme_member_confidence=0.25,
                theme_signal_confirmed=True,
            ),
            _row(
                "unconfirmed",
                market_cap=10_000_000_000.0,
                theme_hot_score=95.0,
                theme_member_confidence=1.0,
                theme_signal_confirmed=False,
            ),
        ]
    )

    scored = score_manual_all_a(
        frame,
        config=ManualAllAConfig(
            score_threshold=0.0,
            weights={**zero_base_weights, "theme_hotness": 1.0},
        ),
    )

    by_id = scored.set_index("security_id")
    assert by_id.loc["core", "manual_theme_hotness_score"] == 80.0
    assert by_id.loc["weak", "manual_theme_hotness_score"] == 20.0
    assert by_id.loc["unconfirmed", "manual_theme_hotness_score"] == 0.0
    assert by_id.loc["core", "manual_all_a_score"] > by_id.loc["weak", "manual_all_a_score"]


def test_ai_quant_profile_exposes_theme_context_for_research() -> None:
    """Verify the AI profile receives theme context for explanation, not trade instruction.

    Returns:
        None: .
    """
    scored = score_manual_all_a(
        pd.DataFrame(
            [
                _row(
                    "300308.SZ",
                    market_cap=120_000_000_000.0,
                    theme_hot_score=82.0,
                    theme_member_confidence=0.9,
                    theme_signal_confirmed=True,
                )
            ]
        ),
        config=ManualAllAConfig(
            score_threshold=0.0,
            weights={**DEFAULT_WEIGHTS, "theme_hotness": 0.05},
        ),
    )

    profile = build_ai_quant_profile(scored.iloc[0])

    assert profile["scores"]["theme_hotness"] is not None
    assert profile["raw_factors"]["theme_hot_score"] == 82.0
    assert profile["raw_factors"]["theme_member_confidence"] == 0.9
    assert profile["raw_factors"]["theme_signal_confirmed"] is True


def test_inactive_theme_weight_does_not_dilute_base_score() -> None:
    """Verify theme weight is neutral when no confirmed member receives a theme score.
    Returns:.

    Returns:
        None: .
    """
    frame = pd.DataFrame(
        [
            _row("a", market_cap=10_000_000_000.0, pe_ttm=9.0),
            _row("b", market_cap=20_000_000_000.0, pe_ttm=12.0),
        ]
    )

    baseline = score_manual_all_a(
        frame,
        config=ManualAllAConfig(score_threshold=0.0, weights=DEFAULT_WEIGHTS),
    ).set_index("security_id")
    themed = score_manual_all_a(
        frame,
        config=ManualAllAConfig(
            score_threshold=0.0,
            weights={
                **{key: value * 0.95 for key, value in DEFAULT_WEIGHTS.items()},
                "theme_hotness": 0.05,
            },
        ),
    ).set_index("security_id")

    assert themed.loc["a", "manual_all_a_score"] == baseline.loc["a", "manual_all_a_score"]
    assert themed.loc["b", "manual_all_a_score"] == baseline.loc["b", "manual_all_a_score"]


def _row(
    security_id: str,
    *,
    market_cap: float,
    pe_ttm: float = 10.0,
    theme_hot_score: float | None = None,
    theme_member_confidence: float | None = None,
    theme_signal_confirmed: bool | None = None,
) -> dict[str, object]:
    """Build one deterministic test cross-section row.

    Args:
        security_id: str: .
        market_cap: float: .
        pe_ttm: float: .
        theme_hot_score: float | None: .
        theme_member_confidence: float | None: .
        theme_signal_confirmed: bool | None: .

    Returns:
        dict[str, object]: .
    """
    row: dict[str, object] = {
        "security_id": security_id,
        "name": security_id,
        "industry_id": "industrial",
        "pe_ttm": pe_ttm,
        "pb": 1.0,
        "ps": 1.2,
        "dividend_yield": 0.04,
        "return_20d": -0.05,
        "return_6m_ex_1m": 0.08,
        "avg_amount_20d": 100_000_000.0,
        "turnover_rate": 0.015,
        "volume_ratio": 1.1,
        "volatility_120d": 0.25,
        "max_drawdown_250d": -0.12,
        "market_cap": market_cap,
    }
    if theme_hot_score is not None:
        row["theme_hot_score"] = theme_hot_score
    if theme_member_confidence is not None:
        row["theme_member_confidence"] = theme_member_confidence
    if theme_signal_confirmed is not None:
        row["theme_signal_confirmed"] = theme_signal_confirmed
    return row
