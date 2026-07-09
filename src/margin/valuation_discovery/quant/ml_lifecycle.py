"""Provider-free ML lifecycle quant scoring.

This module is the production serving side of the offline ML research line. It
does not train models and never calls source providers. It consumes only the
PIT-safe cross-section supplied by ``QuantRepository`` and emits an auditable
score/weight contract for downstream Analysis Mart and Agent use.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import pandas as pd

STRATEGY_FAMILY = "ml_lgbm_lifecycle"
MODEL_FAMILY = "lgbm_lifecycle"
EXECUTION_BOUNDARY = "research_only_no_order"
OFFLINE_PROFILE_ID = "liquid-large-mid-lgbm-recent-trend80-ddstop-v1"

BASE_FEATURES = (
    "roe_ttm",
    "roic_ttm",
    "gross_margin_ttm",
    "net_margin_ttm",
    "ocf_to_net_profit",
    "pe_ttm",
    "pb",
    "ps",
    "dividend_yield",
    "avg_amount_20d",
    "turnover_rate",
    "revenue_yoy",
    "profit_yoy",
    "return_20d",
    "return_6m_ex_1m",
    "return_12m_ex_1m",
    "volatility_120d",
    "max_drawdown_250d",
    "industry_lifecycle_score",
)


@dataclass(frozen=True)
class MLLifecycleConfig:
    """Runtime ML lifecycle serving parameters.."""

    strategy_version: str = "ml-lifecycle-v1"
    max_stock_exposure: float = 0.8
    min_cash: float = 0.2
    top_n: int = 40
    score_temperature: float = 0.20
    exposure_mode: str = "trend80"
    daily_stop_loss: float = 0.0
    daily_drawdown_stop: float = 0.10
    cash_annual: float = 0.03
    pass_threshold: float = 70.0
    near_threshold: float = 60.0
    watch_threshold: float = 50.0
    short_term_overheat_threshold: float = 0.35
    high_volatility_threshold: float = 0.50
    deep_drawdown_threshold: float = -0.30

    @classmethod
    def from_metadata(cls, metadata: dict[str, Any]) -> MLLifecycleConfig:
        """Build config from versioned strategy metadata.

        Args:
            metadata: dict[str, Any]: .

        Returns:
            MLLifecycleConfig: .
        """
        thresholds = metadata.get("thresholds")
        if not isinstance(thresholds, dict):
            thresholds = {}
        return cls(
            strategy_version=str(metadata.get("quant_strategy_version_id") or cls.strategy_version),
            max_stock_exposure=_clamp(
                _number(thresholds.get("max_stock_exposure"), cls.max_stock_exposure),
                0.0,
                1.0,
            ),
            min_cash=_clamp(
                _number(thresholds.get("min_cash"), cls.min_cash),
                0.0,
                1.0,
            ),
            top_n=max(1, int(_number(thresholds.get("top_n"), cls.top_n))),
            score_temperature=_clamp(
                _number(thresholds.get("score_temperature"), cls.score_temperature),
                0.01,
                5.0,
            ),
            exposure_mode=str(thresholds.get("exposure_mode") or cls.exposure_mode),
            daily_stop_loss=_clamp(
                _number(thresholds.get("daily_stop_loss"), cls.daily_stop_loss),
                0.0,
                1.0,
            ),
            daily_drawdown_stop=_clamp(
                _number(
                    thresholds.get("daily_drawdown_stop"),
                    cls.daily_drawdown_stop,
                ),
                0.0,
                1.0,
            ),
            cash_annual=_clamp(
                _number(thresholds.get("cash_annual"), cls.cash_annual),
                0.0,
                1.0,
            ),
            pass_threshold=_number(thresholds.get("pass_threshold"), cls.pass_threshold),
            near_threshold=_number(thresholds.get("near_threshold"), cls.near_threshold),
            watch_threshold=_number(thresholds.get("watch_threshold"), cls.watch_threshold),
            short_term_overheat_threshold=_number(
                thresholds.get("short_term_overheat_threshold"),
                cls.short_term_overheat_threshold,
            ),
            high_volatility_threshold=_number(
                thresholds.get("high_volatility_threshold"),
                cls.high_volatility_threshold,
            ),
            deep_drawdown_threshold=_number(
                thresholds.get("deep_drawdown_threshold"),
                cls.deep_drawdown_threshold,
            ),
        )


def score_ml_lifecycle(
    frame: pd.DataFrame,
    *,
    metadata: dict[str, Any],
) -> pd.DataFrame:
    """Score a PIT-safe cross-section with the ML lifecycle serving contract.

    Args:
        frame: pd.DataFrame: .
        metadata: dict[str, Any]: .

    Returns:
        pd.DataFrame: .
    """
    config = MLLifecycleConfig.from_metadata(metadata)
    scored = frame.copy()
    if scored.empty:
        return scored

    if "security_id" not in scored.columns:
        scored["security_id"] = scored.index.astype(str)

    scored["ml_quality_signal"] = _quality_signal(scored)
    scored["ml_value_signal"] = _value_signal(scored)
    scored["ml_growth_signal"] = _growth_signal(scored)
    scored["ml_momentum_signal"] = _momentum_signal(scored)
    scored["ml_risk_health"] = _risk_health(scored, config=config)
    scored["ml_lifecycle_stage_signal"] = _lifecycle_signal(scored)
    scored["ml_lifecycle_score"] = (
        0.20 * scored["ml_quality_signal"]
        + 0.14 * scored["ml_value_signal"]
        + 0.22 * scored["ml_growth_signal"]
        + 0.18 * scored["ml_momentum_signal"]
        + 0.16 * scored["ml_risk_health"]
        + 0.10 * scored["ml_lifecycle_stage_signal"]
    ).clip(0.0, 100.0)
    scored["ml_risk_reasons"] = [_risk_reasons(row, config=config) for _, row in scored.iterrows()]
    scored["ml_risk_gate"] = [
        "watch" if reasons else "normal" for reasons in scored["ml_risk_reasons"]
    ]
    scored.loc[
        scored["ml_risk_reasons"].map(lambda reasons: "short_term_overheat" in reasons),
        "ml_lifecycle_score",
    ] *= 0.88
    scored.loc[
        scored["ml_risk_reasons"].map(lambda reasons: "high_volatility" in reasons),
        "ml_lifecycle_score",
    ] *= 0.90

    coverage = [_feature_coverage(row) for _, row in scored.iterrows()]
    scored["ml_feature_coverage"] = coverage
    scored["ml_fallback_used"] = [item["coverage_ratio"] < 0.70 for item in coverage]
    scored["ml_score_components"] = [_score_components(row) for _, row in scored.iterrows()]
    scored["ml_risk_controls"] = [
        {
            "risk_gate": row["ml_risk_gate"],
            "risk_reasons": list(row["ml_risk_reasons"]),
            "cash_policy": "min_cash_20pct",
            "max_stock_exposure": config.max_stock_exposure,
            "min_cash": config.min_cash,
            "exposure_mode": config.exposure_mode,
            "daily_stop_loss": config.daily_stop_loss,
            "daily_drawdown_stop": config.daily_drawdown_stop,
        }
        for _, row in scored.iterrows()
    ]
    scored["ml_target_weight"] = _target_weights(scored, config=config)
    return scored


def _quality_signal(frame: pd.DataFrame) -> pd.Series:
    """Process _quality_signal.

    Args:
        frame: pd.DataFrame: .

    Returns:
        pd.Series: .
    """
    return _mean_columns(
        (
            _scale(frame, "roe_ttm", cap=0.20),
            _scale(frame, "roic_ttm", cap=0.16),
            _scale(frame, "gross_margin_ttm", cap=0.45),
            _scale(frame, "net_margin_ttm", cap=0.25),
            _scale(frame, "ocf_to_net_profit", cap=1.20),
        )
    )


def _value_signal(frame: pd.DataFrame) -> pd.Series:
    """Process _value_signal.

    Args:
        frame: pd.DataFrame: .

    Returns:
        pd.Series: .
    """
    return _mean_columns(
        (
            _rank(frame, "pe_ttm", higher=False),
            _rank(frame, "pb", higher=False),
            _rank(frame, "ps", higher=False),
            _rank(frame, "dividend_yield", higher=True),
        )
    )


def _growth_signal(frame: pd.DataFrame) -> pd.Series:
    """Process _growth_signal.

    Args:
        frame: pd.DataFrame: .

    Returns:
        pd.Series: .
    """
    parts = [
        _scale(frame, "revenue_yoy", cap=0.40),
        _scale(frame, "profit_yoy", cap=0.35),
    ]
    if "growth_score" in frame.columns:
        parts.append(_numeric(frame, "growth_score").clip(0.0, 100.0))
    return _mean_columns(tuple(parts))


def _momentum_signal(frame: pd.DataFrame) -> pd.Series:
    """Process _momentum_signal.

    Args:
        frame: pd.DataFrame: .

    Returns:
        pd.Series: .
    """
    parts = [
        _scale(frame, "return_6m_ex_1m", cap=0.30),
        _scale(frame, "return_12m_ex_1m", cap=0.45),
        _scale(frame, "index_relative_momentum", cap=0.20),
        _scale(frame, "industry_relative_momentum", cap=0.20),
        _scale(frame, "ma_trend", cap=0.20),
    ]
    if "momentum_score" in frame.columns:
        parts.append(_numeric(frame, "momentum_score").clip(0.0, 100.0))
    return _mean_columns(tuple(parts))


def _risk_health(frame: pd.DataFrame, *, config: MLLifecycleConfig) -> pd.Series:
    """Process _risk_health.

    Args:
        frame: pd.DataFrame: .
        config: MLLifecycleConfig: .

    Returns:
        pd.Series: .
    """
    volatility = 100.0 * (
        1.0
        - _numeric(frame, "volatility_120d").clip(0.0, config.high_volatility_threshold)
        / config.high_volatility_threshold
    )
    drawdown = 100.0 * (1.0 - (_numeric(frame, "max_drawdown_250d").abs().clip(0.0, 0.45) / 0.45))
    short_return = _numeric(frame, "return_20d")
    overheat_penalty = short_return.gt(config.short_term_overheat_threshold).map(
        {True: 45.0, False: 100.0}
    )
    parts = [volatility, drawdown, overheat_penalty]
    if "risk_score" in frame.columns:
        parts.append(_numeric(frame, "risk_score").clip(0.0, 100.0))
    return _mean_columns(tuple(parts))


def _lifecycle_signal(frame: pd.DataFrame) -> pd.Series:
    """Process _lifecycle_signal.

    Args:
        frame: pd.DataFrame: .

    Returns:
        pd.Series: .
    """
    if "industry_lifecycle_score" in frame.columns:
        return _numeric(frame, "industry_lifecycle_score").clip(0.0, 100.0)
    return _mean_columns((_growth_signal(frame), _momentum_signal(frame)))


def _target_weights(frame: pd.DataFrame, *, config: MLLifecycleConfig) -> pd.Series:
    """Process _target_weights.

    Args:
        frame: pd.DataFrame: .
        config: MLLifecycleConfig: .

    Returns:
        pd.Series: .
    """
    weights = pd.Series(0.0, index=frame.index, dtype="float64")
    eligible = frame[_numeric(frame, "ml_lifecycle_score").ge(config.watch_threshold)].copy()
    if eligible.empty:
        return weights
    eligible = eligible.assign(__security_id_sort=eligible["security_id"].astype(str))
    eligible = eligible.sort_values(
        ["ml_lifecycle_score", "__security_id_sort"],
        ascending=[False, True],
    ).head(config.top_n)
    raw = _softmax(_numeric(eligible, "ml_lifecycle_score"), config.score_temperature)
    if raw.empty:
        return weights
    weights.loc[eligible.index] = raw * _runtime_exposure(frame, config=config)
    return weights


def _risk_reasons(row: pd.Series, *, config: MLLifecycleConfig) -> tuple[str, ...]:
    """Process _risk_reasons.

    Args:
        row: pd.Series: .
        config: MLLifecycleConfig: .

    Returns:
        tuple[str, ...]: .
    """
    reasons: list[str] = []
    ret20 = _row_number(row, "return_20d")
    if ret20 is not None and ret20 > config.short_term_overheat_threshold:
        reasons.append("short_term_overheat")
    volatility = _row_number(row, "volatility_120d")
    if volatility is not None and volatility > config.high_volatility_threshold:
        reasons.append("high_volatility")
    drawdown = _row_number(row, "max_drawdown_250d")
    if drawdown is not None and drawdown < config.deep_drawdown_threshold:
        reasons.append("deep_drawdown")
    return tuple(reasons)


def _feature_coverage(row: pd.Series) -> dict[str, Any]:
    """Process _feature_coverage.

    Args:
        row: pd.Series: .

    Returns:
        dict[str, Any]: .
    """
    missing = [
        feature
        for feature in BASE_FEATURES
        if feature not in row.index or pd.isna(row.get(feature))
    ]
    present = len(BASE_FEATURES) - len(missing)
    return {
        "required_features": list(BASE_FEATURES),
        "present_features": present,
        "missing_features": missing,
        "coverage_ratio": present / len(BASE_FEATURES),
    }


def _score_components(row: pd.Series) -> dict[str, float]:
    """Process _score_components.

    Args:
        row: pd.Series: .

    Returns:
        dict[str, float]: .
    """
    return {
        "ml_lifecycle_score": float(row["ml_lifecycle_score"]),
        "quality_signal": float(row["ml_quality_signal"]),
        "value_signal": float(row["ml_value_signal"]),
        "growth_signal": float(row["ml_growth_signal"]),
        "momentum_signal": float(row["ml_momentum_signal"]),
        "risk_health": float(row["ml_risk_health"]),
        "lifecycle_stage_signal": float(row["ml_lifecycle_stage_signal"]),
    }


def _softmax(scores: pd.Series, temperature: float) -> pd.Series:
    """Return stable softmax weights for a ranked candidate set.

    Args:
        scores: pd.Series: .
        temperature: float: .

    Returns:
        pd.Series: .
    """
    values = pd.to_numeric(scores, errors="coerce").dropna()
    if values.empty:
        return pd.Series(dtype="float64")
    value_range = float(values.max() - values.min())
    if value_range <= 1e-12:
        return pd.Series(1.0 / len(values), index=values.index, dtype="float64")
    normalized = (values - values.min()) / value_range
    logits = normalized / max(float(temperature), 1e-4)
    logits = logits - logits.max()
    exp_values = logits.map(math.exp)
    total = float(exp_values.sum())
    if total <= 0.0:
        return pd.Series(1.0 / len(values), index=values.index, dtype="float64")
    return exp_values / total


def _runtime_exposure(frame: pd.DataFrame, *, config: MLLifecycleConfig) -> float:
    """Return the stock exposure allowed by runtime market-regime features.

    Args:
        frame: pd.DataFrame: .
        config: MLLifecycleConfig: .

    Returns:
        float: .
    """
    cap = min(config.max_stock_exposure, max(0.0, 1.0 - config.min_cash))
    for column in (
        "ml_market_regime_exposure",
        "market_regime_exposure",
        "hs300_trend_exposure",
    ):
        if column not in frame.columns:
            continue
        values = pd.to_numeric(frame[column], errors="coerce").dropna()
        if not values.empty:
            return _clamp(float(values.median()), 0.0, cap)
    return cap


def _scale(frame: pd.DataFrame, column: str, *, cap: float) -> pd.Series:
    """Process _scale.

    Args:
        frame: pd.DataFrame: .
        column: str: .
        cap: float: .

    Returns:
        pd.Series: .
    """
    values = _numeric(frame, column)
    return ((values / cap) * 100.0).clip(0.0, 100.0)


def _rank(frame: pd.DataFrame, column: str, *, higher: bool) -> pd.Series:
    """Process _rank.

    Args:
        frame: pd.DataFrame: .
        column: str: .
        higher: bool: .

    Returns:
        pd.Series: .
    """
    values = _numeric(frame, column)
    if values.notna().sum() == 0:
        return pd.Series(50.0, index=frame.index)
    ranks = values.rank(pct=True, ascending=not higher, na_option="bottom")
    return (ranks * 100.0).clip(0.0, 100.0)


def _numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    """Process _numeric.

    Args:
        frame: pd.DataFrame: .
        column: str: .

    Returns:
        pd.Series: .
    """
    if column not in frame.columns:
        return pd.Series(pd.NA, index=frame.index, dtype="Float64")
    return pd.to_numeric(frame[column], errors="coerce")


def _mean_columns(columns: tuple[pd.Series, ...]) -> pd.Series:
    """Process _mean_columns.

    Args:
        columns: tuple[pd.Series, ...]: .

    Returns:
        pd.Series: .
    """
    if not columns:
        raise ValueError("at least one column is required")
    frame = pd.concat(columns, axis=1)
    return frame.mean(axis=1, skipna=True).fillna(50.0).clip(0.0, 100.0)


def _row_number(row: pd.Series, column: str) -> float | None:
    """Process _row_number.

    Args:
        row: pd.Series: .
        column: str: .

    Returns:
        float | None: .
    """
    try:
        value = float(row.get(column))
    except (TypeError, ValueError):
        return None
    if pd.isna(value):
        return None
    return value


def _number(value: Any, fallback: float) -> float:
    """Process _number.

    Args:
        value: Any: .
        fallback: float: .

    Returns:
        float: .
    """
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return fallback
    if pd.isna(numeric):
        return fallback
    return numeric


def _clamp(value: float, minimum: float, maximum: float) -> float:
    """Process _clamp.

    Args:
        value: float: .
        minimum: float: .
        maximum: float: .

    Returns:
        float: .
    """
    return min(maximum, max(minimum, value))
