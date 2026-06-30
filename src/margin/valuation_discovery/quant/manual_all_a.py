"""Manual All-A quant scoring helpers.

This module keeps the first quant pass broad: no market-cap gate and no top-N
truncation. It ranks the All-A company pool and exposes explainable fields for
the downstream AI research flow, which can later reduce company count and size
allocation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

DEFAULT_WEIGHTS: dict[str, float] = {
    "value": 0.38,
    "dividend": 0.16,
    "reversal": 0.14,
    "liquidity": 0.10,
    "volume_sentiment": 0.08,
    "momentum": 0.08,
    "risk_health": 0.06,
    "theme_hotness": 0.00,
}


@dataclass(frozen=True)
class ManualAllAConfig:
    """Config for the broad All-A manual-rebalance quant pass."""

    score_threshold: float = 52.0
    min_avg_amount_20d: float = 50_000_000.0
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))


def score_manual_all_a(
    frame: pd.DataFrame,
    *,
    config: ManualAllAConfig | None = None,
) -> pd.DataFrame:
    """Return ``frame`` with broad All-A manual strategy scores.

    The function intentionally does not require or filter by ``market_cap``.
    ``market_cap`` can still be included in the AI profile as context.

    Args:
        frame: Source DataFrame with quant feature columns.
        config: Optional manual strategy configuration.

    Returns:
        DataFrame with manual strategy scores, candidate flag, and rank.
    """
    cfg = config or ManualAllAConfig()
    scored = frame.copy()
    if scored.empty:
        return _empty_scored_frame(scored)

    scored["security_id"] = _string_column(scored, "security_id")
    pe = _numeric(scored, "pe_ttm")
    scored["__pe_for_rank"] = pe.where(pe > 0)
    scored["manual_value_score"] = (
        0.45 * _percentile(scored["__pe_for_rank"], higher=False)
        + 0.35 * _percentile(_first_numeric(scored, ("pb",)), higher=False)
        + 0.20 * _percentile(_first_numeric(scored, ("ps", "ps_ttm")), higher=False)
    ).clip(0.0, 100.0)
    scored.loc[pe <= 0, "manual_value_score"] = 0.0
    scored["manual_dividend_score"] = _percentile(
        _first_numeric(scored, ("dividend_yield", "dv_ttm")).fillna(0.0),
        higher=True,
    )
    scored["manual_reversal_score"] = _percentile(
        -_first_numeric(scored, ("return_20d",)),
        higher=True,
    )
    avg_amount = _first_numeric(scored, ("avg_amount_20d",))
    scored["manual_liquidity_score"] = _percentile(np.log1p(avg_amount), higher=True)
    scored["manual_volume_sentiment_score"] = _volume_sentiment_score(scored)
    scored["manual_momentum_score"] = _percentile(
        _first_numeric(scored, ("return_6m_ex_1m",)),
        higher=True,
    )
    scored["manual_risk_health_score"] = _risk_health_score(scored)
    scored["manual_theme_hotness_score"] = _theme_hotness_score(scored)

    weights, theme_weight = _base_and_theme_weights(cfg.weights)
    scored["manual_all_a_score"] = (
        weights["value"] * scored["manual_value_score"]
        + weights["dividend"] * scored["manual_dividend_score"]
        + weights["reversal"] * scored["manual_reversal_score"]
        + weights["liquidity"] * scored["manual_liquidity_score"]
        + weights["volume_sentiment"] * scored["manual_volume_sentiment_score"]
        + weights["momentum"] * scored["manual_momentum_score"]
        + weights["risk_health"] * scored["manual_risk_health_score"]
        + theme_weight * scored["manual_theme_hotness_score"]
    ).clip(0.0, 100.0)
    scored["manual_all_a_candidate"] = (
        scored["manual_all_a_score"] >= cfg.score_threshold
    ) & (avg_amount >= cfg.min_avg_amount_20d)
    scored["__security_id_for_sort"] = scored["security_id"].astype(str)
    scored = scored.sort_values(
        ["manual_all_a_score", "__security_id_for_sort"],
        ascending=[False, True],
    ).reset_index(drop=True)
    scored["manual_all_a_rank"] = np.arange(1, len(scored) + 1)
    return scored.drop(columns=["__pe_for_rank", "__security_id_for_sort"], errors="ignore")


def select_ai_quant_candidates(
    scored: pd.DataFrame,
    *,
    config: ManualAllAConfig | None = None,
) -> pd.DataFrame:
    """Return all broad quant candidates sorted by score.

    This intentionally has no ``top_n`` parameter. The AI research layer should
    make the second-stage company-count and allocation decision.

    Args:
        scored: DataFrame with manual strategy scores.
        config: Optional manual strategy configuration.

    Returns:
        DataFrame of candidate rows sorted by score descending.
    """
    if "manual_all_a_score" not in scored.columns:
        scored = score_manual_all_a(scored, config=config)
    if "manual_all_a_candidate" not in scored.columns:
        cfg = config or ManualAllAConfig()
        avg_amount = _first_numeric(scored, ("avg_amount_20d",))
        scored = scored.copy()
        scored["manual_all_a_candidate"] = (
            scored["manual_all_a_score"] >= cfg.score_threshold
        ) & (avg_amount >= cfg.min_avg_amount_20d)
    candidates = scored.loc[scored["manual_all_a_candidate"]].copy()
    candidates["__security_id_for_sort"] = candidates["security_id"].astype(str)
    return candidates.sort_values(
        ["manual_all_a_score", "__security_id_for_sort"],
        ascending=[False, True],
    ).drop(columns=["__security_id_for_sort"], errors="ignore")


def build_ai_quant_profile(row: pd.Series | dict[str, Any]) -> dict[str, Any]:
    """Build the quant payload consumed by downstream AI research.

    Args:
        row: A scored Series or dict with manual strategy fields.

    Returns:
        A dict with strategy profile, scores, raw factors, and research hints.
    """
    data = row if isinstance(row, pd.Series) else pd.Series(row)
    return {
        "strategy_profile": "manual_all_a_no_market_cap_no_top_n",
        "execution_boundary": "research_only_no_order",
        "candidate": _bool_value(data.get("manual_all_a_candidate")),
        "rank": _optional_int(data.get("manual_all_a_rank")),
        "scores": {
            "manual_all_a_score": _optional_float(data.get("manual_all_a_score")),
            "value": _optional_float(data.get("manual_value_score")),
            "dividend": _optional_float(data.get("manual_dividend_score")),
            "reversal": _optional_float(data.get("manual_reversal_score")),
            "liquidity": _optional_float(data.get("manual_liquidity_score")),
            "volume_sentiment": _optional_float(
                data.get("manual_volume_sentiment_score")
            ),
            "momentum": _optional_float(data.get("manual_momentum_score")),
            "risk_health": _optional_float(data.get("manual_risk_health_score")),
            "theme_hotness": _optional_float(
                data.get("manual_theme_hotness_score")
            ),
        },
        "raw_factors": {
            "pe_ttm": _optional_float(data.get("pe_ttm")),
            "pb": _optional_float(data.get("pb")),
            "ps": _optional_float(data.get("ps", data.get("ps_ttm"))),
            "dividend_yield": _optional_float(
                data.get("dividend_yield", data.get("dv_ttm"))
            ),
            "return_20d": _optional_float(data.get("return_20d")),
            "return_6m_ex_1m": _optional_float(data.get("return_6m_ex_1m")),
            "avg_amount_20d": _optional_float(data.get("avg_amount_20d")),
            "turnover_rate": _optional_float(
                data.get("turnover_rate", data.get("turnover_rate_f"))
            ),
            "volume_ratio": _optional_float(data.get("volume_ratio")),
            "volatility_120d": _optional_float(data.get("volatility_120d")),
            "max_drawdown_250d": _optional_float(data.get("max_drawdown_250d")),
            "market_cap": _optional_float(
                data.get("market_cap", data.get("total_mv"))
            ),
            "theme_code": _optional_string(data.get("theme_code")),
            "theme_name": _optional_string(data.get("theme_name")),
            "theme_source": _optional_string(data.get("theme_source")),
            "theme_hot_score": _optional_float(data.get("theme_hot_score")),
            "theme_member_confidence": _optional_float(
                data.get("theme_member_confidence")
            ),
            "theme_signal_confirmed": _optional_bool(
                data.get("theme_signal_confirmed")
            ),
            "theme_relative_strength_20d": _optional_float(
                data.get("theme_relative_strength_20d")
            ),
            "theme_relative_strength_60d": _optional_float(
                data.get("theme_relative_strength_60d")
            ),
            "theme_amount_ratio_20d": _optional_float(
                data.get("theme_amount_ratio_20d")
            ),
            "theme_breadth_20d": _optional_float(data.get("theme_breadth_20d")),
            "theme_drawdown_60d": _optional_float(
                data.get("theme_drawdown_60d")
            ),
        },
        "research_hints": _research_hints(data),
    }


def _empty_scored_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of frame with empty score columns for the empty case."""
    scored = frame.copy()
    for column in (
        "manual_value_score",
        "manual_dividend_score",
        "manual_reversal_score",
        "manual_liquidity_score",
        "manual_volume_sentiment_score",
        "manual_momentum_score",
        "manual_risk_health_score",
        "manual_theme_hotness_score",
        "manual_all_a_score",
    ):
        scored[column] = pd.Series(dtype=float)
    scored["manual_all_a_candidate"] = pd.Series(dtype=bool)
    scored["manual_all_a_rank"] = pd.Series(dtype=int)
    return scored


def _string_column(frame: pd.DataFrame, column: str) -> pd.Series:
    """Return a string Series for a column, falling back to the index."""
    if column not in frame.columns:
        return frame.index.astype(str).to_series(index=frame.index)
    return frame[column].astype(str)


def _numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    """Return a numeric Series for a column, or NaN if absent."""
    if column not in frame.columns:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce")


def _first_numeric(frame: pd.DataFrame, columns: tuple[str, ...]) -> pd.Series:
    """Return the first available numeric column from a list of candidates."""
    result = pd.Series(np.nan, index=frame.index, dtype=float)
    for column in columns:
        if column not in frame.columns:
            continue
        current = pd.to_numeric(frame[column], errors="coerce")
        result = result.where(result.notna(), current)
    return result


def _percentile(values: pd.Series, *, higher: bool) -> pd.Series:
    """Return winsorized 0-100 percentile scores for a numeric Series."""
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.notna().sum() == 0:
        return pd.Series(0.0, index=numeric.index, dtype=float)
    if numeric.notna().sum() >= 20:
        numeric = numeric.clip(numeric.quantile(0.01), numeric.quantile(0.99))
    rank = numeric.rank(pct=True, method="average", ascending=higher)
    return (rank * 100.0).fillna(0.0).clip(0.0, 100.0)


def _volume_sentiment_score(frame: pd.DataFrame) -> pd.Series:
    """Return a 0-100 volume sentiment score from turnover and volume ratio."""
    turnover = _first_numeric(frame, ("turnover_rate", "turnover_rate_f"))
    turnover_score = _percentile(turnover.fillna(turnover.median()), higher=True)
    volume_ratio = _first_numeric(frame, ("volume_ratio",)).fillna(1.0).clip(0.0, 5.0)
    ratio_score = (
        100.0 - (volume_ratio - 1.2).abs().rank(pct=True, method="average") * 100.0
    ).fillna(0.0)
    return (0.5 * turnover_score + 0.5 * ratio_score).clip(0.0, 100.0)


def _risk_health_score(frame: pd.DataFrame) -> pd.Series:
    """Return a 0-100 risk-health score from volatility, drawdown, and liquidity."""
    volatility = _first_numeric(frame, ("volatility_120d",))
    max_drawdown = _first_numeric(frame, ("max_drawdown_250d",))
    avg_amount = _first_numeric(frame, ("avg_amount_20d",))
    return (
        0.45 * _percentile(volatility, higher=False)
        + 0.35 * _percentile(max_drawdown, higher=True)
        + 0.20 * _percentile(np.log1p(avg_amount), higher=True)
    ).clip(0.0, 100.0)


def _theme_hotness_score(frame: pd.DataFrame) -> pd.Series:
    """Return a 0-100 theme hotness score from theme signal columns."""
    hot_score = _first_numeric(frame, ("theme_hot_score",)).clip(0.0, 100.0)
    confidence = (
        _first_numeric(frame, ("theme_member_confidence",))
        .fillna(0.0)
        .clip(0.0, 1.0)
    )
    confirmed = _bool_series(frame, "theme_signal_confirmed")
    return (hot_score.fillna(0.0) * confidence * confirmed.astype(float)).clip(
        0.0,
        100.0,
    )


def _normalized_weights(weights: dict[str, float]) -> dict[str, float]:
    """Return weights normalized to sum to 1.0, falling back to defaults."""
    merged = {**DEFAULT_WEIGHTS, **weights}
    total = sum(max(0.0, float(value)) for value in merged.values())
    if total <= 0:
        return DEFAULT_WEIGHTS
    return {key: max(0.0, float(value)) / total for key, value in merged.items()}


def _base_and_theme_weights(weights: dict[str, float]) -> tuple[dict[str, float], float]:
    """Split weights into normalized base weights and a separate theme weight."""
    merged = {**DEFAULT_WEIGHTS, **weights}
    theme_weight = max(0.0, float(merged.pop("theme_hotness", 0.0)))
    total = sum(max(0.0, float(value)) for value in merged.values())
    if total <= 0:
        base_weights = {key: 0.0 for key in DEFAULT_WEIGHTS if key != "theme_hotness"}
    else:
        base_weights = {
            key: max(0.0, float(value)) / total
            for key, value in merged.items()
        }
    return base_weights, theme_weight


def _optional_float(value: Any) -> float | None:
    """Convert a value to float, returning None for NaN or non-numeric."""
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(numeric):
        return None
    return numeric


def _optional_int(value: Any) -> int | None:
    """Convert a value to int, returning None for NaN or non-numeric."""
    numeric = _optional_float(value)
    return None if numeric is None else int(numeric)


def _bool_value(value: Any) -> bool:
    """Convert a value to bool, returning False for None or NaN."""
    if value is None or bool(pd.isna(value)):
        return False
    return bool(value)


def _optional_bool(value: Any) -> bool | None:
    """Convert a value to bool, returning None for None or NaN."""
    if value is None or bool(pd.isna(value)):
        return None
    return bool(value)


def _optional_string(value: Any) -> str | None:
    """Convert a value to a stripped string, returning None for empty or NaN."""
    if value is None or bool(pd.isna(value)):
        return None
    text = str(value).strip()
    return text or None


def _bool_series(frame: pd.DataFrame, column: str) -> pd.Series:
    """Return a bool Series for a column, defaulting to False if absent."""
    if column not in frame.columns:
        return pd.Series(False, index=frame.index, dtype=bool)
    return frame[column].map(lambda value: False if pd.isna(value) else bool(value))


def _research_hints(data: pd.Series) -> tuple[str, ...]:
    """Derive structured research hint tags from scored row data."""
    hints: list[str] = []
    return_20d = _optional_float(data.get("return_20d"))
    dividend = _optional_float(data.get("dividend_yield", data.get("dv_ttm")))
    drawdown = _optional_float(data.get("max_drawdown_250d"))
    theme_score = _optional_float(data.get("manual_theme_hotness_score"))
    theme_confirmed = _optional_bool(data.get("theme_signal_confirmed"))
    if return_20d is not None and return_20d < -0.10:
        hints.append("short_term_reversal_candidate")
    if dividend is not None and dividend >= 0.04:
        hints.append("high_dividend_context")
    if drawdown is not None and drawdown < -0.35:
        hints.append("drawdown_risk_requires_review")
    if theme_confirmed and theme_score is not None and theme_score >= 50.0:
        hints.append("confirmed_theme_tilt_requires_business_validation")
    if not hints:
        hints.append("standard_quant_review")
    return tuple(hints)
