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
from margin.agents.runtime.expert_runtime import LLMExpertAgentPlanner
from margin.agents.runtime.main_runtime import (
    LLMMainAgentPlanner,
    MainPlanValidator,
    MainRuntime,
)
from margin.agents.runtime.state_machine import TaskLifecycleState, TaskStateMachine
from margin.agents.runtime.worker_runtime import WorkerRuntime
from margin.agents.security.capability import CapabilityToken
from margin.agents.security.policies import (
    DataAccessPolicy,
    ProductionWritePolicy,
    ToolPolicy,
)
from margin.research.llm import DeterministicLLMProvider


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
        planner=LLMMainAgentPlanner(
            llm_provider=DeterministicLLMProvider(response=_main_plan_response("DataExpertAgent")),
        ),
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


def test_main_runtime_plans_financial_metric_question_to_data_expert() -> None:
    """MainAgent should follow its A2A plan instead of keyword-routing metrics."""
    runtime = MainRuntime(
        domain_cards=default_domain_agent_cards(),
        planner=LLMMainAgentPlanner(
            llm_provider=DeterministicLLMProvider(response=_main_plan_response("DataExpertAgent")),
        ),
        tool_gateway=ExplodingToolGateway(),
    )

    plan = runtime.create_global_plan(
        run_id="run_roe_qna",
        run_type="user_qna",
        user_goal="中国平安最近 ROE 怎么样？",
        context_pack=_context_pack(),
        capability_token=_root_token(),
    )

    assert [task.to_domain_agent for task in plan.domain_tasks] == ["DataExpertAgent"]
    assert plan.domain_tasks[0].task_goal == "Use the selected expert from the A2A plan."
    assert plan.domain_tasks[0].constraints["planned_by"] == "MainAgent"


def test_main_runtime_qna_prompt_uses_agent_cards_not_fixed_routes() -> None:
    """Q&A planning prompt should not hard-code domain routing recipes."""
    llm_provider = _RecordingPlannerLLM(response=_main_plan_response("DataExpertAgent"))
    runtime = MainRuntime(
        domain_cards=default_domain_agent_cards(),
        planner=LLMMainAgentPlanner(llm_provider=llm_provider),
        tool_gateway=ExplodingToolGateway(),
    )

    runtime.create_global_plan(
        run_id="run_open_ended_qna",
        run_type="user_qna",
        user_goal="用户可能提出任意研究问题。",
        context_pack=_context_pack(),
        capability_token=_root_token(),
    )

    prompt = llm_provider.prompts[0]
    assert "domain_agent_catalog" in prompt
    assert "capability_manifest" in prompt
    assert "warehouse_financial_timeseries" in prompt
    assert "warehouse.describe_schema" in prompt
    assert "warehouse.discover_indicators" in prompt
    assert "n_income_attr_p" not in prompt
    assert "Use DataExpertAgent" not in prompt
    assert "Use QuantExpertAgent" not in prompt
    assert "Use EvidenceRagExpertAgent" not in prompt
    assert "Use StockResearchExpertAgent" not in prompt


def test_main_runtime_plans_followup_chart_request_with_recent_context() -> None:
    """Follow-up requests should pass context to the LLM planner."""
    llm_provider = _RecordingPlannerLLM(
        response=_main_plan_response("DataExpertAgent", constraints={"chart_type": "bar"}),
    )
    runtime = MainRuntime(
        domain_cards=default_domain_agent_cards(),
        planner=LLMMainAgentPlanner(llm_provider=llm_provider),
        tool_gateway=ExplodingToolGateway(),
    )

    plan = runtime.create_global_plan(
        run_id="run_roe_followup",
        run_type="user_qna",
        user_goal="画成柱状图",
        context_pack=_context_pack(),
        capability_token=_root_token(),
        conversation_context=(
            {"role": "user", "content": "中国平安最近 ROE 是多少？"},
            {
                "role": "assistant",
                "content": "中国平安最近一期 ROE TTM 为 12.30%。",
            },
        ),
    )

    assert [task.to_domain_agent for task in plan.domain_tasks] == ["DataExpertAgent"]
    assert plan.domain_tasks[0].constraints["chart_type"] == "bar"
    assert "中国平安最近 ROE 是多少" in llm_provider.prompts[0]


def test_main_runtime_plans_scheduled_stock_research_from_prompt_context() -> None:
    """Scheduled stock research should be planned dynamically by MainAgent."""
    runtime = MainRuntime(
        domain_cards=default_domain_agent_cards(),
        planner=LLMMainAgentPlanner(
            llm_provider=DeterministicLLMProvider(
                response={
                    "steps": [
                        {
                            "step_id": "s_data",
                            "agent": "DataExpertAgent",
                            "task": "Check PIT data readiness.",
                            "required_output_types": ["data_readiness"],
                            "constraints": {"phase": "data"},
                        },
                        {
                            "step_id": "s_quant",
                            "agent": "QuantExpertAgent",
                            "task": "Run quant review from PIT features.",
                            "required_output_types": ["quant_result"],
                            "depends_on": ["s_data"],
                        },
                        {
                            "step_id": "s_evidence",
                            "agent": "EvidenceRagExpertAgent",
                            "task": "Prepare RAG evidence for candidates.",
                            "required_output_types": ["evidence_package"],
                            "depends_on": ["s_data"],
                        },
                        {
                            "step_id": "s_stock",
                            "agent": "StockResearchExpertAgent",
                            "task": "Fuse quant and evidence research.",
                            "required_output_types": ["stock_research_context_capsule"],
                            "depends_on": ["s_quant", "s_evidence"],
                        },
                    ],
                    "final_answer_requirements": ["use_approved_capsules_only"],
                }
            ),
        ),
        tool_gateway=ExplodingToolGateway(),
    )

    plan = runtime.create_global_plan(
        run_id="run_sched_v1",
        run_type="scheduled_stock_analysis",
        user_goal=(
            "今天做 A 股研究更新：先检查数据，然后让量化专家和财报增长专家并行研究，"
            "财报线关注业绩大增、供不应求、高景气、超预期和舆情验证，最后融合输出 Dashboard。"
        ),
        context_pack=_context_pack(),
        capability_token=_root_token(),
    )

    agents = [task.to_domain_agent for task in plan.domain_tasks]
    assert agents == [
        "DataExpertAgent",
        "QuantExpertAgent",
        "EvidenceRagExpertAgent",
        "StockResearchExpertAgent",
    ]
    assert plan.planning_prompt_ref == "main_agent_scheduled_planner_v1"
    assert plan.planning_mode == "prompt_dynamic"
    assert {
        (edge["from"], edge["to"]) for edge in plan.domain_dependency_edges
    } >= {
        ("DataExpertAgent", "QuantExpertAgent"),
        ("DataExpertAgent", "EvidenceRagExpertAgent"),
        ("QuantExpertAgent", "StockResearchExpertAgent"),
        ("EvidenceRagExpertAgent", "StockResearchExpertAgent"),
    }


def test_main_runtime_scheduled_prompt_uses_goal_not_fixed_flow() -> None:
    """Scheduled planning prompt should delegate from cards, not prescribe branches."""
    llm_provider = _RecordingPlannerLLM(
        response=_main_plan_response("DataExpertAgent", constraints={"phase": "data"})
    )
    runtime = MainRuntime(
        domain_cards=default_domain_agent_cards(),
        planner=LLMMainAgentPlanner(llm_provider=llm_provider),
        tool_gateway=ExplodingToolGateway(),
    )

    runtime.create_global_plan(
        run_id="run_sched_prompt",
        run_type="scheduled_stock_analysis",
        user_goal="按照今天的研究目标自行规划。",
        context_pack=_context_pack(),
        capability_token=_root_token(),
    )

    prompt = llm_provider.prompts[0]
    assert "domain_agent_catalog" in prompt
    assert "QuantExpertAgent owns" not in prompt
    assert "The quant branch must not" not in prompt
    assert "Fusion must read approved quant" not in prompt


def test_main_plan_validator_rejects_unknown_domain_agent() -> None:
    """Plan validation should block MainAgent hallucinated expert agents."""
    runtime = MainRuntime(
        domain_cards=default_domain_agent_cards(),
        planner=LLMMainAgentPlanner(
            llm_provider=DeterministicLLMProvider(response=_main_plan_response("DataExpertAgent")),
        ),
    )
    plan = runtime.create_global_plan(
        run_id="run_sched_v1",
        run_type="scheduled_stock_analysis",
        user_goal="今天做 A 股研究更新。",
        context_pack=_context_pack(),
        capability_token=_root_token(),
    )
    invalid_task = plan.domain_tasks[0].model_copy(
        update={"to_domain_agent": "ImaginaryExpertAgent"}
    )
    invalid_plan = plan.model_copy(update={"domain_tasks": (invalid_task,)})

    validation = MainPlanValidator(default_domain_agent_cards()).validate(invalid_plan)

    assert validation.valid is False
    assert validation.error_codes == ("unknown_domain_agent",)


def test_expert_runtime_plans_workers_from_worker_cards() -> None:
    """ExpertAgent should dynamically plan worker tasks from visible worker cards."""
    from margin.agents.cards.registry import default_worker_agent_cards

    llm_provider = _RecordingPlannerLLM(
        response={
            "steps": [
                {
                    "step_id": "query",
                    "worker_agent": "DataQuestionWorker",
                    "skill_id": "answer_financial_metric",
                    "task": "Use warehouse tools to answer the user's ROE question.",
                    "required_output_types": [
                        "analysis_table",
                        "computed_metric",
                        "visualization_image",
                    ],
                }
            ],
            "audit_requirements": ["verify_artifacts_before_returning"],
        }
    )
    planner = LLMExpertAgentPlanner(llm_provider=llm_provider)

    worker_plan = planner.plan(
        domain_task=DomainTaskRequest(
            run_id="run_expert",
            domain_task_id="dt_data",
            to_domain_agent="DataExpertAgent",
            domain="data",
            user_intent_summary="中国平安最近 ROE 怎么样？",
            task_goal="Analyze ROE with a generated chart.",
            required_output_types=("analysis_table", "computed_metric", "visualization_image"),
            input_context_pack_ref="ctx_v1",
            capability_token_ref="cap_data",
            token_budget=4000,
            deadline_ms=1000,
            idempotency_key="idem_expert",
        ),
        worker_cards=default_worker_agent_cards(domain="data"),
        context_pack=_context_pack(),
    )

    assert worker_plan.steps[0].worker_agent == "DataQuestionWorker"
    assert worker_plan.steps[0].skill_id == "answer_financial_metric"
    assert "DataQuestionWorker" in llm_provider.prompts[0]
    assert '"input_contract"' in llm_provider.prompts[0]
    assert '"required_fields"' in llm_provider.prompts[0]
    assert '"tool_allowlist"' in llm_provider.prompts[0]
    assert "warehouse.describe_schema" in llm_provider.prompts[0]
    assert "warehouse.discover_indicators" in llm_provider.prompts[0]
    assert "For DataQuestionWorker.answer_financial_metric" in llm_provider.prompts[0]
    assert "current user turn" in llm_provider.prompts[0]
    assert "prior assistant answers" in llm_provider.prompts[0]
    assert "MainAgent" not in worker_plan.steps[0].worker_agent


def _main_plan_response(
    agent_name: str,
    *,
    constraints: dict[str, object] | None = None,
) -> dict[str, object]:
    """Return a deterministic MainAgent structured plan response."""
    return {
        "steps": [
            {
                "step_id": "s1",
                "agent": agent_name,
                "task": "Use the selected expert from the A2A plan.",
                "required_output_types": ["analysis_table"],
                "constraints": constraints or {"planned_by": "MainAgent"},
            }
        ],
        "final_answer_requirements": ["use_approved_capsules_only"],
    }


class _RecordingPlannerLLM(DeterministicLLMProvider):
    """Deterministic planner LLM that records prompts."""

    def __init__(self, response: dict[str, object]) -> None:
        """Initialize with one structured response."""
        super().__init__(response=response)
        self.prompts: list[str] = []

    def complete(self, prompt: str, **kwargs):  # noqa: ANN003, ANN201
        """Record the planning prompt before returning the response."""
        self.prompts.append(prompt)
        return super().complete(prompt, **kwargs)


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
