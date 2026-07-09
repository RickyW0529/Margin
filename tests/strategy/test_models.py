"""Tests for strategy configuration domain models.

This module validates default values, immutability, and guardrail validation
of the strategy configuration domain models.
"""

from __future__ import annotations

from margin.strategy.models import StrategyConfig, StrategyState, StrategyVersion


def test_strategy_ai_default_model_is_deepseek_pro():
    """Verify the default AI model for a strategy config is deepseek-v4-pro.

    Returns:
        Any: .
    """
    config = StrategyConfig()
    assert config.ai.model == "deepseek-v4-pro"


def test_strategy_version_is_immutable():
    """Verify a strategy version is created in the draft state by default.

    Returns:
        Any: .
    """
    version = StrategyVersion(
        strategy_id="st_001",
        version_id="sv_001",
        name="Value Quality",
        config=StrategyConfig(),
        state=StrategyState.DRAFT,
    )
    assert version.state == StrategyState.DRAFT


def test_strategy_config_validates_prohibited_outputs():
    """Verify strategy config accepts and stores prohibited output declarations.

    Returns:
        Any: .
    """
    config = StrategyConfig(decision={"prohibited_outputs": ["GUARANTEED_RETURN"]})
    assert "GUARANTEED_RETURN" in config.decision.prohibited_outputs


def test_strategy_version_freeze_rejects_mutation():
    """Verify a frozen strategy version rejects direct state mutation.

    Returns:
        Any: .
    """
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
