"""Tests for strategy configuration validation and guardrails."""

from __future__ import annotations

from margin.strategy.models import DecisionConfig, StrategyConfig
from margin.strategy.validator import StrategyValidator


def test_validator_accepts_valid_config():
    validator = StrategyValidator()
    config = StrategyConfig()
    ok, errors = validator.validate(config)
    assert ok is True
    assert errors == []


def test_merge_with_guardrails_adds_system_prohibited_outputs():
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
    validator = StrategyValidator()
    config = StrategyConfig(universe=[])
    ok, errors = validator.validate(config)
    assert ok is False
    assert any("universe" in e.lower() for e in errors)
