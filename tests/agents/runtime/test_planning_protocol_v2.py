"""Tests for v2 planner action schemas."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from margin.agents.cards.registry import default_domain_agent_cards
from margin.agents.protocol.models import ContextPack, DomainTaskRequest
from margin.agents.protocol.planning import PlanActionKind
from margin.agents.runtime.expert_runtime import (
    LLMExpertAgentPlanner,
    WorkerPlanStepDraft,
)
from margin.agents.runtime.main_runtime import (
    LLMMainAgentPlanner,
    MainPlanStepDraft,
    MainRuntime,
)
from margin.agents.security.capability import CapabilityToken
from margin.agents.security.policies import (
    DataAccessPolicy,
    ProductionWritePolicy,
    ToolPolicy,
)
from margin.research.llm import DeterministicLLMProvider


def test_main_plan_allows_blocked_without_agent() -> None:
    """Blocked MainAgent steps should not require an ExpertAgent."""
    step = MainPlanStepDraft.model_validate(
        {
            "step_id": "s_quant_blocked",
            "kind": "insufficient_evidence",
            "domain": "quant",
            "reason": "quant capability is not executable",
            "user_safe_message": "当前量化结果模块未注册可执行 worker。",
        }
    )

    assert step.kind is PlanActionKind.INSUFFICIENT_EVIDENCE
    assert step.agent is None


def test_main_plan_delegate_requires_agent() -> None:
    """Delegate steps need an explicit Domain ExpertAgent."""
    with pytest.raises(ValidationError, match="delegate step requires agent"):
        MainPlanStepDraft.model_validate(
            {"step_id": "s1", "kind": "delegate", "task": "Do work."}
        )


def test_main_runtime_can_return_blocked_plan_message_without_domain_task() -> None:
    """MainRuntime should preserve non-delegate plan steps as planner messages."""
    runtime = MainRuntime(
        domain_cards=default_domain_agent_cards(),
        planner=LLMMainAgentPlanner(
            llm_provider=DeterministicLLMProvider(
                response={
                    "steps": [
                        {
                            "step_id": "s_quant_blocked",
                            "kind": "insufficient_evidence",
                            "domain": "quant",
                            "reason": "quant capability is not executable",
                            "user_safe_message": "当前量化结果模块未注册可执行 worker。",
                        }
                    ],
                    "final_answer_requirements": ["state_missing_capability"],
                }
            )
        ),
    )

    plan = runtime.create_global_plan(
        run_id="run_blocked_plan",
        run_type="user_qna",
        user_goal="我的量化结果是什么样？",
        context_pack=_context_pack("run_blocked_plan"),
        capability_token=_token("run_blocked_plan"),
    )

    assert plan.domain_tasks == ()
    assert plan.planner_messages[0]["kind"] == PlanActionKind.INSUFFICIENT_EVIDENCE


def test_worker_plan_can_return_clarification_without_worker_agent() -> None:
    """Clarification WorkerPlan steps should not require worker identity."""
    step = WorkerPlanStepDraft.model_validate(
        {
            "step_id": "w_clarify",
            "kind": "ask_clarification",
            "reason": "missing security_query",
            "missing_inputs": ["security_query"],
            "user_safe_message": "需要先提供公司名称或证券代码。",
        }
    )

    assert step.kind is PlanActionKind.ASK_CLARIFICATION
    assert step.worker_agent is None
    assert step.skill_id is None


def test_worker_plan_execute_requires_worker_and_skill() -> None:
    """Execute WorkerPlan steps need worker identity."""
    with pytest.raises(ValidationError, match="execute step requires worker_agent"):
        WorkerPlanStepDraft.model_validate(
            {"step_id": "w1", "kind": "execute", "task": "Execute."}
        )


def test_expert_planner_accepts_blocked_step_without_visible_workers() -> None:
    """Expert planner should parse blocked plan steps without inventing workers."""
    planner = LLMExpertAgentPlanner(
        llm_provider=DeterministicLLMProvider(
            response={
                "steps": [
                    {
                        "step_id": "w_blocked",
                        "kind": "blocked",
                        "reason": "no executable worker can produce quant_result",
                        "user_safe_message": "当前没有可执行量化 worker。",
                    }
                ]
            }
        )
    )

    plan = planner.plan(
        domain_task=_domain_task(),
        worker_cards=(),
        context_pack=_context_pack("run_expert_blocked"),
    )

    assert plan.steps[0].kind is PlanActionKind.BLOCKED
    assert plan.steps[0].worker_agent is None


def _context_pack(run_id: str) -> ContextPack:
    return ContextPack(
        context_pack_id=f"ctxpack_{run_id}",
        run_id=run_id,
        requester_agent="MainAgent",
        target_agent="MainAgent",
        purpose="test",
        token_budget=4000,
        facts=(),
        compression_policy_version="test",
    )


def _domain_task() -> DomainTaskRequest:
    return DomainTaskRequest(
        run_id="run_expert_blocked",
        domain_task_id="dt_quant",
        to_domain_agent="QuantExpertAgent",
        domain="quant",
        user_intent_summary="我的量化结果是什么样？",
        task_goal="Read quant result.",
        required_output_types=("quant_result",),
        input_context_pack_ref="ctxpack_run_expert_blocked",
        capability_token_ref="cap_quant",
        token_budget=4000,
        deadline_ms=1000,
        idempotency_key="idem",
    )


def _token(run_id: str) -> CapabilityToken:
    return CapabilityToken(
        token_id=f"cap_{run_id}",
        run_id=run_id,
        issued_by="MainAgent",
        issued_to="MainAgent",
        domain="global",
        data_access=(DataAccessPolicy.READ_ANALYSIS_MART,),
        production_write=(ProductionWritePolicy.WRITE_CONTEXT_ONLY,),
        tool_policy=(ToolPolicy.READ_ONLY_TOOLS,),
        allowed_artifact_types=("quant_result",),
        allowed_tool_names=(),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        max_tool_calls=2,
        max_result_bytes=4096,
        can_delegate=True,
        delegation_depth_remaining=2,
    )
