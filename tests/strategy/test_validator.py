"""Tests for strategy configuration validation and guardrails.

This module validates that the strategy validator accepts valid configs,
merges system guardrails, and rejects empty universes.
"""

from __future__ import annotations

from margin.strategy.models import DecisionConfig, StrategyConfig
from margin.strategy.validator import StrategyValidator


def test_validator_accepts_valid_config():
    """Verify the validator accepts a valid default strategy configuration.

    Returns:
        Any: .
    """
    validator = StrategyValidator()
    config = StrategyConfig()
    ok, errors = validator.validate(config)
    assert ok is True
    assert errors == []


def test_merge_with_guardrails_adds_system_prohibited_outputs():
    """Verify merging with guardrails adds system-level prohibited outputs.

    Returns:
        Any: .
    """
    validator = StrategyValidator()
    config = StrategyConfig(
        decision=DecisionConfig(
            research_states=["research_candidate"],
            prohibited_outputs=[],
        )
    )
    merged = validator.merge_with_guardrails(config)
    assert "GUARANTEED_RETURN" in merged.decision.prohibited_outputs
    assert "DIRECT_BUY_SELL_ORDER" in merged.decision.prohibited_outputs


def test_validator_rejects_missing_required_prohibited_outputs_after_merge():
    """Verify the validator accepts a config that becomes valid after guardrail merge.
    Returns:.

    Returns:
        Any: .
    """
    validator = StrategyValidator()
    config = StrategyConfig(
        decision=DecisionConfig(
            research_states=["research_candidate"],
            prohibited_outputs=[],
        )
    )
    ok, errors = validator.validate(config)
    assert ok is True
    merged = validator.merge_with_guardrails(config)
    assert "GUARANTEED_RETURN" in merged.decision.prohibited_outputs


def test_validator_rejects_empty_universe():
    """Verify the validator rejects a config with an empty universe.

    Returns:
        Any: .
    """
    validator = StrategyValidator()
    config = StrategyConfig(universe=[])
    ok, errors = validator.validate(config)
    assert ok is False
    assert any("universe" in e.lower() for e in errors)
