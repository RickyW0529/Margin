"""Tests for ExpertAgent card registry."""

from __future__ import annotations

from margin.agent_runtime.cards import default_agent_card_registry


def test_default_registry_exposes_core_scheduled_experts() -> None:
    registry = default_agent_card_registry()

    assert set(registry.list_names()) >= {
        "DataInspectionAgent",
        "QuantAgent",
        "NewsAcquisitionAgent",
        "StockAnalystAgent",
    }
    assert registry.get("QuantAgent").skills[0].skill_id == (
        "run_ml_lifecycle_quant_analysis"
    )


def test_default_registry_exposes_qna_only_sandbox_expert() -> None:
    registry = default_agent_card_registry()
    sandbox = registry.get("CodeSandboxAgent")

    assert sandbox.skills[0].skill_id == "run_sandboxed_analysis_code"
    assert sandbox.skills[0].schedule_allowed is False
    assert sandbox.skills[0].qa_allowed is True


def test_scheduled_write_agents_are_not_qna_allowed() -> None:
    registry = default_agent_card_registry()

    for agent_name in (
        "DataInspectionAgent",
        "QuantAgent",
        "NewsAcquisitionAgent",
        "StockAnalystAgent",
    ):
        skill = registry.get(agent_name).skills[0]
        assert skill.schedule_allowed is True
        assert skill.qa_allowed is False


def test_main_agent_cannot_discover_internal_tools() -> None:
    registry = default_agent_card_registry()

    assert "quant_screening_tool" not in registry.list_names()
    assert "data_sync_tool" not in registry.list_names()
