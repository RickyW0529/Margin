"""Tests for layered prompt builder.

This module validates that the prompt layer builder assembles guardrails,
custom instructions, and structured layers correctly.
"""

from __future__ import annotations

from margin.strategy.models import StrategyConfig
from margin.strategy.prompt import PromptLayerBuilder


def test_prompt_includes_guardrail_and_custom_instructions():
    """Verify the built prompt contains evidence guardrails and custom instructions.

    Returns:
        None.
    """
    config = StrategyConfig(ai={"custom_instructions": "focus on ROE"})
    prompt = PromptLayerBuilder().build(config)
    assert "evidence" in prompt.lower()
    assert "focus on ROE" in prompt


def test_prompt_contains_no_return_guarantee_guardrail():
    """Verify the prompt includes a no-return-guarantee guardrail.

    Returns:
        None.
    """
    config = StrategyConfig()
    prompt = PromptLayerBuilder().build(config)
    assert "guarantee" in prompt.lower() or "承诺" in prompt


def test_prompt_layers_return_layer_contents():
    """Verify build_layers returns individual named prompt layers.

    Returns:
        None.
    """
    config = StrategyConfig(ai={"custom_instructions": "test"})
    layers = PromptLayerBuilder().build_layers(config)
    layer_names = {layer.layer for layer in layers}
    assert "system_guardrail" in layer_names
    assert "user_custom" in layer_names
