"""Tests for strategy service."""

from __future__ import annotations

import pytest

from margin.strategy.models import StrategyConfig, StrategyState
from margin.strategy.repository import MemoryStrategyRepository
from margin.strategy.service import StrategyService


def _service() -> StrategyService:
    return StrategyService(repository=MemoryStrategyRepository())


def test_service_creates_strategy_from_template():
    service = _service()
    profile = service.create_from_template("user_1", "value_quality")
    assert profile.active_version_id == ""
    assert len(profile.versions) == 1
    assert profile.versions[0].name == "价值质量"


def test_service_creates_custom_strategy():
    service = _service()
    config = StrategyConfig(universe=["000001.SZ"])
    profile = service.create_custom("user_1", config, "My Strategy")
    assert profile.name == "My Strategy"
    assert profile.versions[0].config.universe == ["000001.SZ"]


def test_service_update_creates_new_version():
    service = _service()
    profile = service.create_from_template("user_1", "value_quality")
    updated = service.update_strategy(
        profile.strategy_id,
        config_delta={"universe": ["000002.SZ"]},
    )
    assert len(updated.versions) == 2


def test_service_update_deep_merges_nested_config_delta():
    service = _service()
    profile = service.create_from_template("user_1", "value_quality")

    updated = service.update_strategy(
        profile.strategy_id,
        config_delta={"risk": {"max_position_weight": 0.05}},
    )

    risk = updated.versions[-1].config.risk
    assert risk.max_position_weight == 0.05
    assert risk.max_sector_weight == profile.versions[0].config.risk.max_sector_weight


def test_service_validate_version_transitions_to_validating():
    service = _service()
    profile = service.create_from_template("user_1", "value_quality")
    version = profile.versions[0]
    validated = service.validate_version(profile.strategy_id, version.version_id)
    assert validated.versions[0].state == StrategyState.BACKTESTING


def test_service_activate_version_sets_active():
    service = _service()
    profile = service.create_from_template("user_1", "value_quality")
    version = profile.versions[0]
    service.validate_version(profile.strategy_id, version.version_id)
    service.backtest_version(profile.strategy_id, version.version_id)
    paper_traded = service.paper_trade_version(profile.strategy_id, version.version_id)
    assert paper_traded.active_version_id == ""
    assert paper_traded.versions[0].state == StrategyState.PAPER_TRADING
    activated = service.activate_version(profile.strategy_id, version.version_id)
    assert activated.active_version_id == version.version_id
    assert activated.versions[0].state == StrategyState.ACTIVE


def test_service_get_prompt_returns_string():
    service = _service()
    profile = service.create_from_template("user_1", "value_quality")
    prompt = service.get_prompt(profile.strategy_id, profile.versions[0].version_id)
    assert isinstance(prompt, str)
    assert "guardrail" in prompt.lower()


def test_service_list_templates():
    service = _service()
    templates = service.list_templates()
    assert len(templates) == 6


def test_service_missing_strategy_raises():
    service = _service()
    with pytest.raises(KeyError):
        service.get_profile("missing")
