"""Tests for MainAgentRuntime planning boundaries."""

from __future__ import annotations

import pytest

from margin.agent_runtime.cards import default_agent_card_registry
from margin.agent_runtime.context_store import MemoryAgentContextStore, make_context_artifact
from margin.agent_runtime.guardrails import GuardrailDecisionType
from margin.agent_runtime.main_agent import MainAgentPlanningError, MainAgentRuntime
from margin.agent_runtime.step_definitions import load_scheduled_stock_analysis_flow
from margin.agents.runtime.executor_registry import default_qna_executor_registry
from margin.research.llm import DeterministicLLMProvider


def _runtime() -> MainAgentRuntime:
    return MainAgentRuntime(
        context_store=MemoryAgentContextStore(),
        card_registry=default_agent_card_registry(),
        scheduled_flow=load_scheduled_stock_analysis_flow(),
    )


def test_create_scheduled_plan_uses_fixed_json_steps() -> None:
    result = _runtime().create_scheduled_stock_analysis_plan(
        run_id="ar_sched",
        user_intent_summary="daily scheduled research",
    )

    assert result.guardrail_decision.decision == GuardrailDecisionType.ALLOW
    assert [step.step_id for step in result.plan.steps] == [
        "data_inspection",
        "quant_analysis",
        "performance_growth_scout",
        "rag_coverage_gate",
        "fundamental_analysis",
        "sentiment_monitor",
        "fusion_research",
        "main_agent_final_review",
    ]
    assert result.plan.fixed_flow is True
    assert result.plan.steps[0].expert_agent_name == "DataInspectionAgent"
    assert result.plan.steps[1].input_artifact_refs == ("data_readiness",)
    assert result.plan.steps[2].input_artifact_refs == ("data_readiness",)


def test_create_scheduled_plan_blocks_guaranteed_return_intent() -> None:
    result = _runtime().create_scheduled_stock_analysis_plan(
        run_id="ar_sched_blocked",
        user_intent_summary="每天推荐保证收益的股票",
    )

    assert result.guardrail_decision.decision == GuardrailDecisionType.DENY
    assert result.plan.steps == ()


def test_final_review_blocks_when_required_artifacts_missing() -> None:
    runtime = _runtime()
    planned = runtime.create_scheduled_stock_analysis_plan(
        run_id="ar_sched_review",
        user_intent_summary="daily scheduled research",
    )

    review = runtime.final_review(run_id=planned.plan.run_id)

    assert review.decision == "blocked"
    assert "data_readiness" in review.missing_artifacts


def test_final_review_completes_when_required_artifacts_exist() -> None:
    context_store = MemoryAgentContextStore()
    runtime = MainAgentRuntime(
        context_store=context_store,
        card_registry=default_agent_card_registry(),
        scheduled_flow=load_scheduled_stock_analysis_flow(),
    )
    planned = runtime.create_scheduled_stock_analysis_plan(
        run_id="ar_sched_complete",
        user_intent_summary="daily scheduled research",
    )
    expected_producers = {
        "data_readiness": "DataInspectionAgent",
        "quant_result": "QuantAgent",
        "analysis_mart_snapshot": "QuantAgent",
        "fundamental_thesis_snapshot": "FundamentalAnalystAgent",
        "sentiment_delta_report": "SentimentMonitorAgent",
        "fusion_research_result": "FusionResearchAgent",
        "dashboard_projection_event": "FusionResearchAgent",
    }
    for artifact_type, producer_agent in expected_producers.items():
        context_store.add_artifact(
            make_context_artifact(
                artifact_id=f"ctx_{artifact_type}",
                run_id=planned.plan.run_id,
                artifact_type=artifact_type,
                producer_agent=producer_agent,
                payload_json={"ok": True},
            )
        )

    review = runtime.final_review(run_id=planned.plan.run_id)

    assert review.decision == "complete"
    assert review.missing_artifacts == ()
    assert review.invalid_artifacts == ()
    assert review.audit_report_ref is not None
    audit = context_store.get_artifact(review.audit_report_ref)
    assert audit is not None
    assert audit.artifact_type == "final_audit_report"


def test_create_user_qna_plan_hides_sandbox_without_executor() -> None:
    provider = DeterministicLLMProvider(
        response={
            "plan_id": "plan_ar_qna_visual",
            "fixed_flow": False,
            "steps": [
                {
                    "expert_agent_name": "DataAnalystAgent",
                    "skill_id": "answer_with_analysis_artifacts",
                },
                {
                    "expert_agent_name": "CodeSandboxAgent",
                    "skill_id": "run_sandboxed_analysis_code",
                },
            ],
        }
    )
    runtime = MainAgentRuntime(
        context_store=MemoryAgentContextStore(),
        card_registry=default_agent_card_registry(),
        scheduled_flow=load_scheduled_stock_analysis_flow(),
        llm_provider_factory=lambda: provider,
    )

    result = runtime.create_user_qna_plan(
        run_id="ar_qna",
        user_input="给我看一下今日推荐详情，并生成一个关键指标对比图",
    )

    assert result.guardrail_decision.decision == GuardrailDecisionType.ALLOW
    assert result.plan.fixed_flow is False
    assert [step.expert_agent_name for step in result.plan.steps] == [
        "DataAnalystAgent",
    ]
    assert result.plan.steps[0].skill_id == "answer_with_analysis_artifacts"


def test_create_user_qna_plan_uses_llm_card_selection_for_greeting() -> None:
    provider = DeterministicLLMProvider(
        response={
            "plan_id": "plan_ar_qna_greeting",
            "fixed_flow": False,
            "steps": [
                {
                    "expert_agent_name": "GeneralQnaAgent",
                    "skill_id": "answer_general_qna",
                }
            ],
        }
    )
    runtime = MainAgentRuntime(
        context_store=MemoryAgentContextStore(),
        card_registry=default_agent_card_registry(),
        scheduled_flow=load_scheduled_stock_analysis_flow(),
        llm_provider_factory=lambda: provider,
    )

    result = runtime.create_user_qna_plan(
        run_id="ar_qna_greeting",
        user_input="你好",
    )

    assert result.guardrail_decision.decision == GuardrailDecisionType.ALLOW
    assert result.plan.fixed_flow is False
    assert [step.expert_agent_name for step in result.plan.steps] == [
        "GeneralQnaAgent",
    ]
    assert result.plan.steps[0].skill_id == "answer_general_qna"


def test_create_user_qna_plan_rejects_llm_selected_write_agents() -> None:
    provider = DeterministicLLMProvider(
        response={
            "plan_id": "plan_ar_qna_bad",
            "fixed_flow": False,
            "steps": [
                {
                    "expert_agent_name": "DataInspectionAgent",
                    "skill_id": "inspect_data_readiness",
                },
                {
                    "expert_agent_name": "QuantAgent",
                    "skill_id": "run_ml_lifecycle_quant_analysis",
                },
            ],
        }
    )
    runtime = MainAgentRuntime(
        context_store=MemoryAgentContextStore(),
        card_registry=default_agent_card_registry(),
        scheduled_flow=load_scheduled_stock_analysis_flow(),
        llm_provider_factory=lambda: provider,
    )

    with pytest.raises(MainAgentPlanningError, match="no valid Q&A expert"):
        runtime.create_user_qna_plan(
            run_id="ar_qna_recommendation",
            user_input="今日推荐股票是什么？",
        )


def test_create_user_qna_plan_can_use_sandbox_after_executor_registration() -> None:
    provider = DeterministicLLMProvider(
        response={
            "plan_id": "plan_ar_qna_visual",
            "fixed_flow": False,
            "steps": [
                {
                    "expert_agent_name": "DataAnalystAgent",
                    "skill_id": "answer_with_analysis_artifacts",
                },
                {
                    "expert_agent_name": "CodeSandboxAgent",
                    "skill_id": "run_sandboxed_analysis_code",
                },
            ],
        }
    )
    registry = default_qna_executor_registry()
    registry.register(
        agent_name="CodeSandboxAgent",
        skill_id="run_sandboxed_analysis_code",
        executor=object(),
    )
    runtime = MainAgentRuntime(
        context_store=MemoryAgentContextStore(),
        card_registry=default_agent_card_registry(),
        scheduled_flow=load_scheduled_stock_analysis_flow(),
        llm_provider_factory=lambda: provider,
        executor_registry=registry,
    )

    result = runtime.create_user_qna_plan(
        run_id="ar_qna",
        user_input="给我看一下今日推荐详情，并生成一个关键指标对比图",
    )

    assert result.guardrail_decision.decision == GuardrailDecisionType.ALLOW
    assert [step.expert_agent_name for step in result.plan.steps] == [
        "DataAnalystAgent",
        "CodeSandboxAgent",
    ]


def test_create_user_qna_plan_fails_when_llm_planner_unavailable() -> None:
    provider = DeterministicLLMProvider(fail=True, error="planner down")
    runtime = MainAgentRuntime(
        context_store=MemoryAgentContextStore(),
        card_registry=default_agent_card_registry(),
        scheduled_flow=load_scheduled_stock_analysis_flow(),
        llm_provider_factory=lambda: provider,
    )

    with pytest.raises(MainAgentPlanningError, match="planner down"):
        runtime.create_user_qna_plan(
            run_id="ar_qna_planner_down",
            user_input="你好",
        )


def test_create_user_qna_plan_blocks_guaranteed_return_question() -> None:
    result = _runtime().create_user_qna_plan(
        run_id="ar_qna_blocked",
        user_input="今天推荐哪只股票可以保证收益？",
    )

    assert result.guardrail_decision.decision == GuardrailDecisionType.DENY
    assert result.plan.steps == ()
