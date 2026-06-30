"""Tests for strategy sandbox.

This module validates that the strategy sandbox flags invalid configurations
and passes valid ones.
"""

from __future__ import annotations

from margin.strategy.models import StrategyConfig
from margin.strategy.sandbox import StrategySandbox


def test_sandbox_flags_missing_evidence():
    """Verify the sandbox flags a config with insufficient evidence requirements.

    Returns:
        None.
    """
    result = StrategySandbox().evaluate(StrategyConfig(evidence={"min_evidence_count": 0}))
    assert not result.validation_ok


def test_sandbox_passes_valid_config():
    """Verify the sandbox passes a valid default strategy configuration.

    Returns:
        None.
    """
    result = StrategySandbox().evaluate(StrategyConfig())
    assert result.validation_ok
    assert result.sample_run_ok
    assert result.data_leak_ok


def test_sandbox_fails_empty_universe():
    """Verify the sandbox fails a config with an empty universe.

    Returns:
        None.
    """
    result = StrategySandbox().evaluate(StrategyConfig(universe=[]))
    assert not result.validation_ok
    assert any("universe" in m.lower() for m in result.messages)
