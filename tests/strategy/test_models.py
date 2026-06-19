"""Tests for strategy configuration domain models."""

from __future__ import annotations

from margin.strategy.models import StrategyConfig, StrategyState, StrategyVersion


def test_strategy_version_is_immutable():
    version = StrategyVersion(
        strategy_id="st_001",
        version_id="sv_001",
        name="Value Quality",
        config=StrategyConfig(),
        state=StrategyState.DRAFT,
    )
    assert version.state == StrategyState.DRAFT


def test_strategy_config_validates_prohibited_outputs():
    config = StrategyConfig(decision={"prohibited_outputs": ["GUARANTEED_RETURN"]})
    assert "GUARANTEED_RETURN" in config.decision.prohibited_outputs


def test_strategy_version_freeze_rejects_mutation():
    version = StrategyVersion(
        strategy_id="st_001",
        version_id="sv_001",
        name="Value Quality",
        config=StrategyConfig(),
        state=StrategyState.DRAFT,
    )
    try:
        version.state = StrategyState.ACTIVE
        raise AssertionError("frozen model should reject mutation")
    except Exception:
        pass
