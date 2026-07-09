"""test_runtime_v1 module."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from margin.agent_runtime.step_definitions import load_scheduled_stock_analysis_flow
from margin.agents.cards.registry import default_domain_agent_cards
from margin.agents.protocol.models import (
    AgentExecutionStatus,
    ContextFact,
    ContextPack,
    DomainTaskRequest,
    WorkerTaskResult,
)
from margin.agents.runtime.adapters_v0 import map_v0_flow_to_domain_tasks
from margin.agents.runtime.audit_pipeline import AuditPipeline
from margin.agents.runtime.domain_runtime import DomainRuntime
from margin.agents.runtime.executor_registry import ExecutorRegistry
from margin.agents.runtime.main_runtime import MainRuntime
from margin.agents.runtime.state_machine import TaskLifecycleState, TaskStateMachine
from margin.agents.runtime.worker_runtime import WorkerRuntime
from margin.agents.security.capability import CapabilityToken
from margin.agents.security.policies import (
    DataAccessPolicy,
    ProductionWritePolicy,
    ToolPolicy,
)


def _root_token() -> CapabilityToken:
    """_root_token implementation.

    Returns:
        CapabilityToken: .
    """
    return CapabilityToken(
        token_id="cap_root",
        run_id="run_v1",
        issued_by="MainAgent",
        issued_to="MainAgent",
        domain="global",
        data_access=(
            DataAccessPolicy.READ_CHAT_SUMMARY,
            DataAccessPolicy.READ_DASHBOARD,
            DataAccessPolicy.READ_ANALYSIS_MART,
            DataAccessPolicy.READ_EVIDENCE,
            DataAccessPolicy.READ_PROVIDER_STATUS,
        ),
        production_write=(ProductionWritePolicy.WRITE_CONTEXT_ONLY,),
        tool_policy=(
            ToolPolicy.READ_ONLY_TOOLS,
            ToolPolicy.QUANT_TOOLS,
            ToolPolicy.RETRIEVAL_TOOLS,
            ToolPolicy.DATA_SYNC_TOOLS,
        ),
        allowed_artifact_types=(
            "explanation",
            "data_readiness",
            "quant_result",
            "evidence_package",
            "stock_research_context_capsule",
        ),
        allowed_tool_names=("context.safe_read_artifact", "quant.run_screen"),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        max_tool_calls=8,
        max_result_bytes=4096,
        can_delegate=True,
        delegation_depth_remaining=2,
    )


def _context_pack() -> ContextPack:
    """_context_pack implementation.

    Returns:
        ContextPack: .
    """
    return ContextPack(
        context_pack_id="ctx_v1",
        run_id="run_v1",
        requester_agent="MainAgent",
        target_agent="MainAgent",
        purpose="main_planning",
        token_budget=4000,
        facts=(
            ContextFact(
                fact_id="fact_question",
                statement="用户询问当前数据是否新鲜。",
                confidence=1,
                fact_type="user_constraint",
            ),
        ),
        compression_policy_version="test-v1",
    )


class ExplodingToolGateway:
    """Worker gateway that intentionally blocks any call through this helper.."""

    def call(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN201
        """Process tool call invocation for the exploding gateway.

        Args:
            *_args: Any: .
            **_kwargs: Any: .

        Returns:
            Any: .
        """
        raise AssertionError("L1 runtime must not call tools directly")


def test_state_machine_rejects_invalid_transition() -> None:
    """test_state_machine_rejects_invalid_transition implementation.

    Returns:
        None: .
    """
    machine = TaskStateMachine()

    state = machine.transition(TaskLifecycleState.CREATED, TaskLifecycleState.PLANNED)

    assert state is TaskLifecycleState.PLANNED
    with pytest.raises(ValueError, match="invalid task transition"):
        machine.transition(TaskLifecycleState.CREATED, TaskLifecycleState.SUCCEEDED)


def test_main_runtime_does_not_call_tools_and_creates_domain_tasks() -> None:
    """test_main_runtime_does_not_call_tools_and_creates_domain_tasks implementation.

    Returns:
        None: .
    """
    runtime = MainRuntime(
        domain_cards=default_domain_agent_cards(),
        tool_gateway=ExplodingToolGateway(),
    )

    plan = runtime.create_global_plan(
        run_id="run_v1",
        run_type="user_qna",
        user_goal="当前数据是否新鲜？",
        context_pack=_context_pack(),
        capability_token=_root_token(),
    )

    assert plan.created_by == "MainAgent"
    assert plan.run_type == "user_qna"
    assert plan.domain_tasks
    assert all(task.from_agent == "MainAgent" for task in plan.domain_tasks)
    assert all(task.to_domain_agent.endswith("ExpertAgent") for task in plan.domain_tasks)


def test_domain_runtime_derives_narrower_worker_token() -> None:
    """test_domain_runtime_derives_narrower_worker_token implementation.

    Returns:
        None: .
    """
    runtime = DomainRuntime(expert_agent_name="QuantExpertAgent")
    parent = _root_token().model_copy(
        update={
            "issued_to": "QuantExpertAgent",
            "domain": "quant",
            "data_access": (DataAccessPolicy.READ_ANALYSIS_MART,),
            "tool_policy": (ToolPolicy.QUANT_TOOLS,),
            "allowed_tool_names": ("quant.run_screen",),
            "can_delegate": True,
            "delegation_depth_remaining": 1,
        }
    )
    request = DomainTaskRequest(
        run_id="run_v1",
        domain_task_id="dt_quant",
        to_domain_agent="QuantExpertAgent",
        domain="quant",
        user_intent_summary="run quant screen",
        task_goal="生成量化候选",
        required_output_types=("quant_result",),
        input_context_pack_ref="ctx_v1",
        capability_token_ref=parent.token_id,
        token_budget=4000,
        deadline_ms=1000,
        idempotency_key="idem_domain",
    )

    worker_tasks = runtime.create_worker_tasks(
        domain_request=request,
        parent_token=parent,
        worker_agent_name="QuantScreenWorker",
        skill_id="run_screen",
        required_output_types=("quant_result",),
    )

    assert len(worker_tasks) == 1
    assert worker_tasks[0].worker_agent == "QuantScreenWorker"
    assert worker_tasks[0].required_output_types == ("quant_result",)
    assert runtime.issued_tokens[worker_tasks[0].capability_token_ref].can_delegate is False
    assert runtime.issued_tokens[worker_tasks[0].capability_token_ref].tool_policy == (
        ToolPolicy.QUANT_TOOLS,
    )


def test_worker_runtime_blocks_unregistered_executor() -> None:
    """test_worker_runtime_blocks_unregistered_executor implementation.

    Returns:
        None: .
    """
    registry = ExecutorRegistry()
    runtime = WorkerRuntime(executor_registry=registry)
    request = DomainRuntime(expert_agent_name="QuantExpertAgent").create_worker_tasks(
        domain_request=DomainTaskRequest(
            run_id="run_v1",
            domain_task_id="dt_quant",
            to_domain_agent="QuantExpertAgent",
            domain="quant",
            user_intent_summary="run quant screen",
            task_goal="生成量化候选",
            required_output_types=("quant_result",),
            input_context_pack_ref="ctx_v1",
            capability_token_ref="cap_parent",
            token_budget=4000,
            deadline_ms=1000,
            idempotency_key="idem_domain",
        ),
        parent_token=_root_token().model_copy(
            update={
                "issued_to": "QuantExpertAgent",
                "domain": "quant",
                "data_access": (DataAccessPolicy.READ_ANALYSIS_MART,),
                "tool_policy": (ToolPolicy.QUANT_TOOLS,),
                "allowed_tool_names": ("quant.run_screen",),
                "can_delegate": True,
                "delegation_depth_remaining": 1,
            }
        ),
        worker_agent_name="QuantScreenWorker",
        skill_id="run_screen",
        required_output_types=("quant_result",),
    )[0]

    result = runtime.execute(request)

    assert result.status is AgentExecutionStatus.BLOCKED
    assert result.error_code == "executor_not_registered"


def test_worker_runtime_success_requires_required_artifacts() -> None:
    """test_worker_runtime_success_requires_required_artifacts implementation.

    Returns:
        None: .
    """
    registry = ExecutorRegistry()

    def executor(_request):
        """Execute executor logic.

        Args:
            _request: Any: .

        Returns:
            Any: .
        """
        return WorkerTaskResult(
            run_id="run_v1",
            domain_task_id="dt_quant",
            worker_task_id="wt_quant",
            worker_agent="QuantScreenWorker",
            skill_id="run_screen",
            status=AgentExecutionStatus.SUCCEEDED,
            output_artifact_refs=("artifact_quant",),
            safe_summary="ok",
        )

    registry.register(
        agent_name="QuantScreenWorker",
        skill_id="run_screen",
        executor=executor,
    )
    runtime = WorkerRuntime(executor_registry=registry)
    request = DomainRuntime(expert_agent_name="QuantExpertAgent").create_worker_tasks(
        domain_request=DomainTaskRequest(
            run_id="run_v1",
            domain_task_id="dt_quant",
            to_domain_agent="QuantExpertAgent",
            domain="quant",
            user_intent_summary="run quant screen",
            task_goal="生成量化候选",
            required_output_types=("quant_result",),
            input_context_pack_ref="ctx_v1",
            capability_token_ref="cap_parent",
            token_budget=4000,
            deadline_ms=1000,
            idempotency_key="idem_domain",
        ),
        parent_token=_root_token().model_copy(
            update={
                "issued_to": "QuantExpertAgent",
                "domain": "quant",
                "data_access": (DataAccessPolicy.READ_ANALYSIS_MART,),
                "tool_policy": (ToolPolicy.QUANT_TOOLS,),
                "allowed_tool_names": ("quant.run_screen",),
                "can_delegate": True,
                "delegation_depth_remaining": 1,
            }
        ),
        worker_agent_name="QuantScreenWorker",
        skill_id="run_screen",
        required_output_types=("quant_result",),
    )[0]

    result = runtime.execute(request)

    assert result.status is AgentExecutionStatus.SUCCEEDED
    assert result.output_artifact_refs == ("artifact_quant",)


def test_final_audit_rejects_missing_lineage() -> None:
    """test_final_audit_rejects_missing_lineage implementation.

    Returns:
        None: .
    """
    auditor = AuditPipeline()

    report = auditor.audit_final_answer(
        run_id="run_v1",
        required_artifact_refs=("artifact_quant",),
        available_artifacts={},
        approved_capsule_refs=(),
    )

    assert report.final_answer_allowed is False
    assert report.decision == "blocked"
    assert "artifact_quant" in report.missing_artifacts


def test_scheduled_v05_maps_to_v1_domain_tasks() -> None:
    """test_scheduled_v05_maps_to_v1_domain_tasks implementation.

    Returns:
        None: .
    """
    flow = load_scheduled_stock_analysis_flow()

    tasks = map_v0_flow_to_domain_tasks(
        flow,
        run_id="run_sched_v1",
        context_pack_ref="ctx_sched",
        capability_token_ref="cap_sched",
    )

    assert tasks
    assert {task.domain_task_id for task in tasks} >= {
        "dt_data_inspection",
        "dt_quant_analysis",
        "dt_fusion_research",
    }
    assert all(task.to_domain_agent.endswith("ExpertAgent") for task in tasks)
