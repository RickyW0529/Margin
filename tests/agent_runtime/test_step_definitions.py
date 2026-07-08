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
        "performance_growth_scout",
        "rag_coverage_gate",
        "fundamental_analysis",
        "sentiment_monitor",
        "fusion_research",
        "main_agent_final_review",
    ]
    assert [step.order for step in flow.steps] == [1, 2, 2, 3, 4, 5, 6, 7]


def test_scheduled_flow_declares_artifact_dependencies() -> None:
    flow = load_scheduled_stock_analysis_flow()
    by_id = {step.step_id: step for step in flow.steps}

    assert by_id["quant_analysis"].required_artifacts == ("data_readiness",)
    assert "news_context_bundle" not in by_id["quant_analysis"].required_artifacts
    assert by_id["performance_growth_scout"].required_artifacts == ("data_readiness",)
    assert by_id["rag_coverage_gate"].required_artifacts == (
        "fundamental_target_pool",
    )
    assert by_id["fundamental_analysis"].required_artifacts == (
        "fundamental_target_pool",
        "rag_coverage_report",
        "indexed_document_batch",
    )
    assert by_id["sentiment_monitor"].required_artifacts == (
        "fundamental_thesis_snapshot",
    )
    assert by_id["fusion_research"].required_artifacts == (
        "quant_result",
        "analysis_mart_snapshot",
        "fundamental_thesis_snapshot",
        "sentiment_delta_report",
    )
    assert "dashboard_projection_event" in by_id["fusion_research"].produced_artifacts
    assert by_id["main_agent_final_review"].expert_agent == "MainAgent"


def test_scheduled_flow_has_parallel_quant_and_fundamental_branches() -> None:
    flow = load_scheduled_stock_analysis_flow()

    waves = [
        tuple(step.step_id for step in wave)
        for wave in flow.dependency_waves()
    ]

    assert waves[:3] == [
        ("data_inspection",),
        ("quant_analysis", "performance_growth_scout"),
        ("rag_coverage_gate",),
    ]
    assert "fusion_research" in waves[-2]


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
