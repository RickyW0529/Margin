"""Theme hotness helpers for manual-rebalance quant strategies."""

from __future__ import annotations

from collections.abc import Hashable, Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class ThemeSignalConfig:
    """Hysteresis and scaling config for theme hotness signals.."""

    entry_score: float = 70.0
    entry_confirmation_periods: int = 2
    exit_score: float = 55.0
    exit_confirmation_periods: int = 2


def score_theme_components(
    *,
    relative_strength_20d: float,
    relative_strength_60d: float,
    amount_ratio_20d: float,
    breadth_20d: float,
    drawdown_60d: float,
) -> float:
    """Return a 0-100 theme hotness score from PIT market components.

    Args:
        relative_strength_20d: float: .
        relative_strength_60d: float: .
        amount_ratio_20d: float: .
        breadth_20d: float: .
        drawdown_60d: float: .

    Returns:
        float: .
    """
    strength_20d = _linear_score(relative_strength_20d, low=-0.05, high=0.20)
    strength_60d = _linear_score(relative_strength_60d, low=-0.10, high=0.40)
    amount_score = _linear_score(amount_ratio_20d, low=0.80, high=2.00)
    breadth_score = _clip(breadth_20d * 100.0, 0.0, 100.0)
    drawdown_penalty = _linear_score(abs(drawdown_60d), low=0.05, high=0.30)
    score = (
        0.40 * strength_20d
        + 0.25 * strength_60d
        + 0.20 * amount_score
        + 0.15 * breadth_score
        - 0.15 * drawdown_penalty
    )
    return _clip(score, 0.0, 100.0)


def confirmation_states(
    scores: Iterable[tuple[Hashable, float]],
    *,
    config: ThemeSignalConfig | None = None,
) -> dict[Hashable, bool]:
    """Return active states after entry/exit hysteresis over ordered scores.

    Args:
        scores: Iterable[tuple[Hashable, float]]: .
        config: ThemeSignalConfig | None: .

    Returns:
        dict[Hashable, bool]: .
    """
    cfg = config or ThemeSignalConfig()
    active = False
    hot_streak = 0
    weak_streak = 0
    states: dict[Hashable, bool] = {}
    for key, score in scores:
        if active:
            if score < cfg.exit_score:
                weak_streak += 1
            else:
                weak_streak = 0
            if weak_streak >= cfg.exit_confirmation_periods:
                active = False
                hot_streak = 0
        else:
            if score >= cfg.entry_score:
                hot_streak += 1
            else:
                hot_streak = 0
            if hot_streak >= cfg.entry_confirmation_periods:
                active = True
                weak_streak = 0
        states[key] = active
    return states


def _linear_score(value: float, *, low: float, high: float) -> float:
    """Return a 0-100 linear interpolation score between low and high bounds.

    Args:
        value: float: .
        low: float: .
        high: float: .

    Returns:
        float: .
    """
    if high <= low:
        raise ValueError("high must be greater than low")
    return _clip((float(value) - low) / (high - low) * 100.0, 0.0, 100.0)


def _clip(value: float, low: float, high: float) -> float:
    """Clamp a value to the [low, high] range.

    Args:
        value: float: .
        low: float: .
        high: float: .

    Returns:
        float: .
    """
    return min(high, max(low, float(value)))
