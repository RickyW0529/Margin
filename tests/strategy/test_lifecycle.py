"""Tests for strategy lifecycle state machine.

This module validates the allowed and rejected state transitions of the
strategy lifecycle, ensuring versions move through the correct states.
"""

from __future__ import annotations

import pytest

from margin.strategy.lifecycle import StrategyLifecycle
from margin.strategy.models import StrategyConfig, StrategyState, StrategyVersion


def test_draft_can_validate():
    """Verify a draft strategy version can transition to validating state.

    Returns:
        None.
    """
    lifecycle = StrategyLifecycle()
    assert lifecycle.can_transition(StrategyState.DRAFT, StrategyState.VALIDATING)


def test_active_can_archive():
    """Verify an active strategy version can transition to archived state.

    Returns:
        None.
    """
    lifecycle = StrategyLifecycle()
    assert lifecycle.can_transition(StrategyState.ACTIVE, StrategyState.ARCHIVED)


def test_draft_cannot_activate():
    """Verify a draft strategy version cannot skip directly to active state.

    Returns:
        None.
    """
    lifecycle = StrategyLifecycle()
    assert not lifecycle.can_transition(StrategyState.DRAFT, StrategyState.ACTIVE)


def test_transition_returns_updated_version():
    """Verify transition returns a new version with the updated state.

    Returns:
        None.
    """
    lifecycle = StrategyLifecycle()
    version = StrategyVersion(
        strategy_id="st_1",
        version_id="sv_1",
        name="V1",
        config=StrategyConfig(),
        state=StrategyState.DRAFT,
    )
    updated = lifecycle.transition(version, StrategyState.VALIDATING)
    assert updated.state == StrategyState.VALIDATING


def test_invalid_transition_raises():
    """Verify an invalid state transition raises a ValueError.

    Returns:
        None.
    """
    lifecycle = StrategyLifecycle()
    version = StrategyVersion(
        strategy_id="st_1",
        version_id="sv_1",
        name="V1",
        config=StrategyConfig(),
        state=StrategyState.DRAFT,
    )
    with pytest.raises(ValueError):
        lifecycle.transition(version, StrategyState.ACTIVE)
