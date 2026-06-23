"""Tests for layered prompt builder."""

from __future__ import annotations

from margin.strategy.models import StrategyConfig
from margin.strategy.prompt import PromptLayerBuilder


def test_prompt_includes_guardrail_and_custom_instructions():
    """prompt includes guardrail and custom instructions."""
    config = StrategyConfig(ai={"custom_instructions": "focus on ROE"})
    prompt = PromptLayerBuilder().build(config)
    assert "evidence" in prompt.lower()
    assert "focus on ROE" in prompt


def test_prompt_contains_no_return_guarantee_guardrail():
    """prompt contains no return guarantee guardrail."""
    config = StrategyConfig()
    prompt = PromptLayerBuilder().build(config)
    assert "guarantee" in prompt.lower() or "承诺" in prompt


def test_prompt_layers_return_layer_contents():
    """prompt layers return layer contents."""
    config = StrategyConfig(ai={"custom_instructions": "test"})
    layers = PromptLayerBuilder().build_layers(config)
    layer_names = {layer.layer for layer in layers}
    assert "system_guardrail" in layer_names
    assert "user_custom" in layer_names
