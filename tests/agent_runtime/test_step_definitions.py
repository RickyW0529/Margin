"""Tests for fixed agent step definitions."""

from __future__ import annotations

import json
from importlib.resources import files

from margin.agent_runtime.step_definitions import load_scheduled_stock_analysis_flow


def test_scheduled_flow_is_fixed_and_ordered() -> None:
    flow = load_scheduled_stock_analysis_flow()

    assert flow.flow_id == "scheduled_stock_analysis"
    assert flow.fixed_flow is True
    assert [step.step_id for step in flow.steps] == [
        "data_inspection",
        "quant_analysis",
        "news_acquisition",
        "stock_analysis",
        "main_agent_final_review",
    ]
    assert [step.order for step in flow.steps] == [1, 2, 3, 4, 5]


def test_scheduled_flow_declares_artifact_dependencies() -> None:
    flow = load_scheduled_stock_analysis_flow()
    by_id = {step.step_id: step for step in flow.steps}

    assert by_id["quant_analysis"].required_artifacts == ("data_readiness",)
    assert "quant_result" in by_id["news_acquisition"].required_artifacts
    assert "citation_validation_report" in by_id["stock_analysis"].produced_artifacts
    assert by_id["main_agent_final_review"].expert_agent == "MainAgent"


def test_scheduled_flow_bundles_json_schema_resource() -> None:
    scheduled = json.loads(
        files("margin.agent_runtime.flows")
        .joinpath("scheduled_stock_analysis_steps.json")
        .read_text(encoding="utf-8")
    )
    schema = json.loads(
        files("margin.agent_runtime.flows")
        .joinpath("step_schema.json")
        .read_text(encoding="utf-8")
    )

    assert scheduled["$schema"] == "./step_schema.json"
    assert schema["properties"]["$schema"]["type"] == "string"
