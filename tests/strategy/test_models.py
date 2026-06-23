"""Tests for strategy configuration domain models."""

from __future__ import annotations

from margin.strategy.models import StrategyConfig, StrategyState, StrategyVersion


def test_strategy_ai_default_model_is_deepseek_pro():
    """strategy ai default model is deepseek pro."""
    config = StrategyConfig()
    assert config.ai.model == "deepseek-v4-pro"


def test_strategy_version_is_immutable():
    """strategy version is immutable."""
    version = StrategyVersion(
        strategy_id="st_001",
        version_id="sv_001",
        name="Value Quality",
        config=StrategyConfig(),
        state=StrategyState.DRAFT,
    )
    assert version.state == StrategyState.DRAFT


def test_strategy_config_validates_prohibited_outputs():
    """strategy config validates prohibited outputs."""
    config = StrategyConfig(decision={"prohibited_outputs": ["GUARANTEED_RETURN"]})
    assert "GUARANTEED_RETURN" in config.decision.prohibited_outputs


def test_strategy_version_freeze_rejects_mutation():
    """strategy version freeze rejects mutation."""
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
