"""Tests for strategy lifecycle state machine."""

from __future__ import annotations

import pytest

from margin.strategy.lifecycle import StrategyLifecycle
from margin.strategy.models import StrategyConfig, StrategyState, StrategyVersion


def test_draft_can_validate():
    lifecycle = StrategyLifecycle()
    assert lifecycle.can_transition(StrategyState.DRAFT, StrategyState.VALIDATING)


def test_active_can_archive():
    lifecycle = StrategyLifecycle()
    assert lifecycle.can_transition(StrategyState.ACTIVE, StrategyState.ARCHIVED)


def test_draft_cannot_activate():
    lifecycle = StrategyLifecycle()
    assert not lifecycle.can_transition(StrategyState.DRAFT, StrategyState.ACTIVE)


def test_transition_returns_updated_version():
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
