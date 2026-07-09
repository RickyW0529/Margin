"""Theme tilt scoring tests.

This module validates that theme component scoring rewards strength and
penalizes drawdown, and that confirmation states apply entry and exit
hysteresis correctly.
"""

from __future__ import annotations

from margin.valuation_discovery.quant.theme_tilt import (
    ThemeSignalConfig,
    confirmation_states,
    score_theme_components,
)


def test_score_theme_components_rewards_strength_and_penalizes_drawdown() -> None:
    """Verify theme score combines relative strength, volume, breadth, and drawdown.

    Returns:
        None: .
    """
    strong = score_theme_components(
        relative_strength_20d=0.16,
        relative_strength_60d=0.30,
        amount_ratio_20d=1.8,
        breadth_20d=0.75,
        drawdown_60d=-0.08,
    )
    risky = score_theme_components(
        relative_strength_20d=0.16,
        relative_strength_60d=0.30,
        amount_ratio_20d=1.8,
        breadth_20d=0.75,
        drawdown_60d=-0.32,
    )

    assert strong > 70.0
    assert risky < strong


def test_confirmation_states_adds_entry_and_exit_hysteresis() -> None:
    """Verify theme confirmation requires two hot periods and two weak periods to exit.

    Returns:
        None: .
    """
    states = confirmation_states(
        [
            ("2026-01", 72.0),
            ("2026-02", 74.0),
            ("2026-03", 58.0),
            ("2026-04", 52.0),
            ("2026-05", 54.0),
        ],
        config=ThemeSignalConfig(
            entry_score=70.0,
            entry_confirmation_periods=2,
            exit_score=55.0,
            exit_confirmation_periods=2,
        ),
    )

    assert states["2026-01"] is False
    assert states["2026-02"] is True
    assert states["2026-03"] is True
    assert states["2026-04"] is True
    assert states["2026-05"] is False
