"""Contracts for the v1 application-facing Agent runtime service."""

from __future__ import annotations

import inspect
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

from margin.agent_runtime.context_store import MemoryAgentContextStore, SQLAlchemyAgentContextStore
from margin.agent_runtime.db_models import (
    AgentRuntimeArtifactRow,
    AgentRuntimeGuardrailDecisionRow,
    AgentRuntimeRunRow,
    AgentRuntimeStepRow,
)
from margin.agents.context.repository import MemoryContextRepository
from margin.agents.protocol.models import AgentExecutionStatus
from margin.agents.runtime.service import (
    AgentRuntimeService,
    UserQnaCommand,
)
from margin.dashboard.models import ResearchItem, ResearchRun
from margin.dashboard.repository import MemoryDashboardRepository
from margin.dashboard.service import DashboardServiceBundle
from margin.data.warehouse_repository import IndicatorHistoryValue, SecurityProfileValue
from margin.research.llm import DeterministicLLMProvider, LLMResult
from margin.storage.base import Base
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)

DECISION_AT = datetime(2026, 6, 22, tzinfo=UTC)


def test_v1_user_qna_service_creates_plan_and_final_answer_artifact() -> None:
    """User Q&A should run through v1 plan/capsule/final-answer objects."""
    from margin.agents.runtime.service import AgentRuntimeService, UserQnaCommand

    context_store = MemoryAgentContextStore()
    context_repository = MemoryContextRepository()
    dashboard_services = _dashboard_services()
    llm_provider = _SequencedLLMProvider(
        main_plan=_main_plan("GeneralQnaExpertAgent"),
        expert_plan=_expert_plan("GeneralQnaWorker", "answer_general_qna"),
        answers=("当前研究候选包含 000001.SZ。",),
    )
    service = AgentRuntimeService(
        context_store=context_store,
        context_repository=context_repository,
        dashboard_services=dashboard_services,
        llm_provider_factory=lambda: llm_provider,
    )

    result = service.run_user_qna(
        UserQnaCommand(
            run_id="ar_qna_v1",
            scope_version_id="scope-1",
            message="今日研究候选有哪些？",
            universe="ALL_A",
            language="zh",
            conversation_context=(),
        )
    )

    assert result.guardrail.allowed is True
    assert result.global_plan.created_by == "MainAgent"
    assert result.global_plan.run_type == "user_qna"
    assert result.global_plan.domain_tasks
    assert all(task.from_agent == "MainAgent" for task in result.global_plan.domain_tasks)
    assert all(step.expert_agent_name.endswith("ExpertAgent") for step in result.trace_steps)
    assert result.final_answer.answer_text == "当前研究候选包含 000001.SZ。"
    assert result.final_answer.final_audit_report_ref == "fa_ar_qna_v1"
    tool_records = service._tool_gateway._audit_store.records.values()  # noqa: SLF001
    assert [record.tool_name for record in tool_records] == ["dashboard.read_candidates"]
    assert context_repository.get_context_pack("ctxpack_ar_qna_v1_mainagent") is not None
    assert context_repository.get_domain_capsule("dcc_ar_qna_v1_general") is not None
    assert {
        (edge.from_ref, edge.to_ref, edge.edge_type)
        for edge in context_repository.list_lineage_edges("ar_qna_v1")
    } >= {
        ("ctxpack_ar_qna_v1_mainagent", "chat_summary:e3b0c44298fc1c14", "source_ref"),
        ("dcc_ar_qna_v1_general", "ctxpack_ar_qna_v1_mainagent", "source_ref"),
    }
    artifact_ids = {artifact.artifact_id for artifact in result.artifacts}
    assert result.final_answer.artifact_id in artifact_ids
    assert context_store.get_artifact(result.final_answer.artifact_id) is not None
    assert any(artifact.artifact_type == "analysis_table" for artifact in result.artifacts)
    assert llm_provider.calls == ["main_plan", "expert_plan", "answer"]


def test_v1_user_qna_service_strips_model_thinking_blocks() -> None:
    """User-visible Q&A answers must not expose model reasoning blocks."""
    service = AgentRuntimeService(
        context_store=MemoryAgentContextStore(),
        context_repository=MemoryContextRepository(),
        dashboard_services=_dashboard_services(),
        llm_provider_factory=lambda: _SequencedLLMProvider(
            main_plan=_main_plan("GeneralQnaExpertAgent"),
            expert_plan=_expert_plan("GeneralQnaWorker", "answer_general_qna"),
            answers=("<think>hidden reasoning</think>\n\n你好，我是 Margin。",),
        ),
    )

    result = service.run_user_qna(
        UserQnaCommand(
            run_id="ar_qna_think",
            scope_version_id="scope-1",
            message="你好",
            universe="ALL_A",
            language="zh",
            conversation_context=(),
        )
    )

    assert result.answer == "你好，我是 Margin。"
    assert "<think>" not in result.final_answer.answer_text


def test_v1_user_qna_service_formats_long_final_answer_as_markdown() -> None:
    """WritingAgent should format long user-facing answers as readable Markdown."""
    service = AgentRuntimeService(
        context_store=MemoryAgentContextStore(),
        context_repository=MemoryContextRepository(),
        dashboard_services=_dashboard_services(),
        llm_provider_factory=lambda: _SequencedLLMProvider(
            main_plan=_main_plan("GeneralQnaExpertAgent"),
            expert_plan=_expert_plan("GeneralQnaWorker", "answer_general_qna"),
            answers=(
                "当前没有可用的研究候选。你可以先补充公司名称、财务指标或研究范围。"
                "系统会基于已批准的数据和证据回答，不会直接给出交易指令。",
            ),
        ),
    )

    result = service.run_user_qna(
        UserQnaCommand(
            run_id="ar_qna_markdown_writer",
            scope_version_id="scope-1",
            message="你好，帮我看看当前能做什么",
            universe="ALL_A",
            language="zh",
            conversation_context=(),
        )
    )

    assert result.answer.startswith("### 回答")
    assert "- 当前没有可用的研究候选。" in result.answer
    assert "交易指令" in result.answer
    artifact_by_type = {artifact.artifact_type: artifact for artifact in result.artifacts}
    assert artifact_by_type["writing_revision"].producer_agent == "WritingAgent"
    assert artifact_by_type["writing_revision"].payload_json["output_format"] == "markdown"


def test_v1_user_qna_service_answers_financial_metric_with_data_artifacts() -> None:
    """ROE questions should use DataExpert/DataQuestionWorker warehouse reads."""
    warehouse = _FinancialMetricWarehouse()
    llm_provider = _SequencedLLMProvider(
        main_plan=_main_plan("DataExpertAgent"),
        expert_plan=_expert_plan(
            "DataQuestionWorker",
            "answer_financial_metric",
            worker_inputs=_roe_worker_inputs("中国平安最近 ROE 怎么样？"),
        ),
        answers=(),
    )
    service = AgentRuntimeService(
        context_store=MemoryAgentContextStore(),
        context_repository=MemoryContextRepository(),
        dashboard_services=_dashboard_services(),
        llm_provider_factory=lambda: llm_provider,
        warehouse_repository=warehouse,
    )

    result = service.run_user_qna(
        UserQnaCommand(
            run_id="ar_qna_roe",
            scope_version_id="scope-1",
            message="中国平安最近 ROE 怎么样？",
            universe="ALL_A",
            language="zh",
            conversation_context=(),
        )
    )

    assert result.global_plan.domain_tasks[0].to_domain_agent == "DataExpertAgent"
    assert result.trace_steps[0].expert_agent_name == "DataExpertAgent"
    assert result.trace_steps[0].skill_id == "answer_financial_metric"
    assert "中国平安" in result.answer
    assert "ROE TTM" in result.answer
    assert "12.30%" in result.answer
    assert service._startup_contract_report.valid is True  # noqa: SLF001
    tool_records = service._tool_gateway._audit_store.records.values()  # noqa: SLF001
    assert [record.tool_name for record in tool_records] == [
        "warehouse.describe_schema",
        "warehouse.resolve_security",
        "warehouse.discover_indicators",
        "warehouse.query_indicator_history",
    ]
    assert llm_provider.calls == ["main_plan", "expert_plan"]
    assert warehouse.indicator_queries
    assert warehouse.indicator_queries[0].indicator_ids == ("roe_ttm",)
    artifact_by_type = {artifact.artifact_type: artifact for artifact in result.artifacts}
    assert artifact_by_type["analysis_table"].payload_json["rows"][-1]["value"] == 12.3
    assert artifact_by_type["chart_spec"].payload_json["series"][0]["metric"] == "roe_ttm"
    assert artifact_by_type["computed_metric"].payload_json["latest_value"] == 12.3
    assert artifact_by_type["visualization_image"].payload_json["image_format"] == "svg"


def test_v1_user_qna_service_uses_inline_current_user_for_metric_lookup() -> None:
    """Single-line role-marked transcripts must not become warehouse queries."""
    transcript = (
        "user: 你好 assistant: 你好！ 我是 Margin 的本地投研助手。"
        "current_user: 我想看一下中国平安银行的roe"
    )
    warehouse = _FinancialMetricWarehouse()
    llm_provider = _SequencedLLMProvider(
        main_plan=_main_plan("DataExpertAgent"),
        expert_plan=_expert_plan(
            "DataQuestionWorker",
            "answer_financial_metric",
            worker_inputs={
                "user_query": transcript,
                "security_query": transcript,
                "indicator_id": "roe_ttm",
                "chart_type": "line",
            },
        ),
        answers=(),
    )
    service = AgentRuntimeService(
        context_store=MemoryAgentContextStore(),
        context_repository=MemoryContextRepository(),
        dashboard_services=_dashboard_services(),
        llm_provider_factory=lambda: llm_provider,
        warehouse_repository=warehouse,
    )

    result = service.run_user_qna(
        UserQnaCommand(
            run_id="ar_qna_inline_transcript",
            scope_version_id="scope-1",
            message=transcript,
            universe="ALL_A",
            language="zh",
            conversation_context=(
                {"role": "user", "content": "你好"},
                {
                    "role": "assistant",
                    "content": "没有在当前 PIT 数据仓库中找到 user: 你好 的 ROE TTM 历史记录。",
                },
            ),
        )
    )

    assert warehouse.security_queries == ["中国平安银行"]
    assert "中国平安" in result.answer
    assert "assistant:" not in result.answer
    assert "current_user:" not in result.answer
    assert "user: 你好" not in result.answer


def test_v1_user_qna_service_does_not_reuse_previous_metric_for_chart_only_followup() -> None:
    """Chart-only follow-ups must not reuse previous ROE intent as executable input."""
    warehouse = _FinancialMetricWarehouse()
    llm_provider = _SequencedLLMProvider(
        main_plan=_main_plan("DataExpertAgent", task="Use data tools with recent chat context."),
        expert_plan=_expert_plan(
            "DataQuestionWorker",
            "answer_financial_metric",
            task="Use recent context and render the requested bar chart.",
            worker_inputs=_roe_worker_inputs("画成柱状图", chart_type="bar"),
        ),
        answers=(),
    )
    service = AgentRuntimeService(
        context_store=MemoryAgentContextStore(),
        context_repository=MemoryContextRepository(),
        dashboard_services=_dashboard_services(),
        llm_provider_factory=lambda: llm_provider,
        warehouse_repository=warehouse,
    )

    result = service.run_user_qna(
        UserQnaCommand(
            run_id="ar_qna_roe_bar",
            scope_version_id="scope-1",
            message="画成柱状图",
            universe="ALL_A",
            language="zh",
            conversation_context=(
                {"role": "user", "content": "中国平安最近 ROE 是多少？"},
                {
                    "role": "assistant",
                    "content": "中国平安最近一期 ROE TTM 为 12.30%。",
                },
            ),
        )
    )

    assert result.global_plan.domain_tasks[0].to_domain_agent == "DataExpertAgent"
    assert result.trace_steps[0].skill_id == "answer_financial_metric"
    assert llm_provider.calls == ["main_plan", "expert_plan"]
    artifact_by_type = {artifact.artifact_type: artifact for artifact in result.artifacts}
    assert artifact_by_type["chart_spec"].payload_json["input_valid"] is False
    assert artifact_by_type["visualization_image"].payload_json["input_valid"] is False
    assert warehouse.indicator_queries == []
    assert "请直接输入" in result.answer


def test_v1_user_qna_service_executes_all_main_planned_domain_tasks() -> None:
    """Runtime should execute every DomainTask selected by MainAgent."""
    warehouse = _FinancialMetricWarehouse()
    llm_provider = _SequencedLLMProvider(
        main_plan={
            "steps": [
                {
                    "step_id": "s_data",
                    "agent": "DataExpertAgent",
                    "task": "查询中国平安 ROE，并返回数据产物。",
                    "required_output_types": [
                        "qna_answer",
                        "analysis_table",
                        "computed_metric",
                        "visualization_image",
                    ],
                },
                {
                    "step_id": "s_general",
                    "agent": "GeneralQnaExpertAgent",
                    "task": "结合已批准上下文整理用户可读总结。",
                    "required_output_types": ["qna_answer", "analysis_table"],
                    "depends_on": ["s_data"],
                },
            ],
            "final_answer_requirements": ["use_approved_capsules_only"],
        },
        expert_plan=(
            _expert_plan(
                "DataQuestionWorker",
                "answer_financial_metric",
                required_output_types=(
                    "qna_answer",
                    "analysis_table",
                    "computed_metric",
                    "visualization_image",
                ),
                worker_inputs=_roe_worker_inputs("中国平安最近 ROE 怎么样？"),
            ),
            _expert_plan("GeneralQnaWorker", "answer_general_qna"),
        ),
        answers=("综合看，中国平安 ROE 数据已整理完成。",),
    )
    context_repository = MemoryContextRepository()
    service = AgentRuntimeService(
        context_store=MemoryAgentContextStore(),
        context_repository=context_repository,
        dashboard_services=_dashboard_services(),
        llm_provider_factory=lambda: llm_provider,
        warehouse_repository=warehouse,
    )

    result = service.run_user_qna(
        UserQnaCommand(
            run_id="ar_qna_multi_domain",
            scope_version_id="scope-1",
            message="中国平安最近 ROE 怎么样？再整理成用户能看的总结。",
            universe="ALL_A",
            language="zh",
            conversation_context=(),
        )
    )

    assert llm_provider.calls == ["main_plan", "expert_plan", "expert_plan", "answer"]
    assert [step.expert_agent_name for step in result.trace_steps] == [
        "DataExpertAgent",
        "GeneralQnaExpertAgent",
    ]
    assert result.final_answer.used_domain_capsule_refs == (
        "dcc_ar_qna_multi_domain_data",
        "dcc_ar_qna_multi_domain_general",
    )
    assert context_repository.get_domain_capsule("dcc_ar_qna_multi_domain_data") is not None
    assert context_repository.get_domain_capsule("dcc_ar_qna_multi_domain_general") is not None
    assert "### 综合回答" in result.answer
    assert "#### DataExpertAgent" in result.answer
    assert "#### GeneralQnaExpertAgent" in result.answer
    assert "ROE TTM" in result.answer
    assert "综合看，中国平安 ROE 数据已整理完成。" in result.answer


def test_v1_user_qna_service_persists_run_before_postgres_artifacts(
    database_url: str,
) -> None:
    """PostgreSQL artifact writes require the AgentRun parent row first."""
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    with session_factory.begin() as session:
        for row in (
            AgentRuntimeGuardrailDecisionRow,
            AgentRuntimeArtifactRow,
            AgentRuntimeStepRow,
            AgentRuntimeRunRow,
        ):
            session.query(row).delete()
    context_store = SQLAlchemyAgentContextStore(session_factory)
    service = AgentRuntimeService(
        context_store=context_store,
        context_repository=MemoryContextRepository(),
        dashboard_services=_dashboard_services(),
        llm_provider_factory=lambda: _SequencedLLMProvider(
            main_plan=_main_plan("GeneralQnaExpertAgent"),
            expert_plan=_expert_plan("GeneralQnaWorker", "answer_general_qna"),
            answers=("你好，我是 Margin。",),
        ),
    )

    try:
        result = service.run_user_qna(
            UserQnaCommand(
                run_id="ar_qna_pg",
                scope_version_id="scope-1",
                message="你好",
                universe="ALL_A",
                language="zh",
                conversation_context=(),
            )
        )

        assert context_store.get_run("ar_qna_pg") is not None
        assert context_store.get_artifact(result.final_answer.artifact_id) is not None
    finally:
        with session_factory.begin() as session:
            for row in (
                AgentRuntimeGuardrailDecisionRow,
                AgentRuntimeArtifactRow,
                AgentRuntimeStepRow,
                AgentRuntimeRunRow,
            ):
                session.query(row).delete()
        engine.dispose()


def test_api_route_no_longer_imports_legacy_main_agent_execution() -> None:
    """The HTTP route should depend on the v1 runtime service, not v0 executors."""
    import margin.api.routes.agent_runtime as route_module

    source = inspect.getsource(route_module)

    assert "get_agent_runtime_service" in source
    assert "MainAgentRuntime" not in source
    assert "DataAnalystAgent" not in source
    assert "GeneralQnaAgent" not in source
    assert "_execute_user_qna_plan" not in source


def test_v1_user_qna_service_does_not_directly_select_data_worker() -> None:
    """Service must execute the worker selected by ExpertAgent planning."""
    import margin.agents.runtime.service as service_module

    source = inspect.getsource(service_module.AgentRuntimeService)

    assert "_build_financial_metric_analysis" not in source
    assert "question_mode" not in source
    assert "financial_metric_analysis" not in source


def test_agent_runtime_service_has_no_worker_name_if_else_dispatch() -> None:
    """Worker execution must go through WorkerRuntime instead of service branches."""
    import margin.agents.runtime.service as service_module

    source = inspect.getsource(service_module.AgentRuntimeService._execute_worker_task)

    assert 'worker_task.worker_agent == "DataQuestionWorker"' not in source
    assert 'worker_task.worker_agent == "GeneralQnaWorker"' not in source
    assert "_worker_runtime.execute" in source


def test_main_planner_only_sees_executable_domains() -> None:
    """Main planner domain catalog should be filtered by CapabilityRegistry."""
    llm_provider = _SequencedLLMProvider(
        main_plan=_main_plan("GeneralQnaExpertAgent"),
        expert_plan=_expert_plan("GeneralQnaWorker", "answer_general_qna"),
        answers=("你好，我是 Margin。",),
    )
    service = AgentRuntimeService(
        context_store=MemoryAgentContextStore(),
        context_repository=MemoryContextRepository(),
        dashboard_services=_dashboard_services(),
        llm_provider_factory=lambda: llm_provider,
        warehouse_repository=None,
    )

    service.run_user_qna(
        UserQnaCommand(
            run_id="ar_qna_visible_domains",
            scope_version_id="scope-1",
            message="你好",
            universe="ALL_A",
            language="zh",
            conversation_context=(),
        )
    )

    main_prompt = llm_provider.prompts[0]

    assert '"domain_agent_names":["GeneralQnaExpertAgent"]' in main_prompt
    assert '"context_status"' in main_prompt
    assert '"capability_snapshot"' in main_prompt


def test_expert_planner_only_sees_executable_worker_skills() -> None:
    """Main planner should not create domain tasks for hidden worker skills."""
    llm_provider = _SequencedLLMProvider(
        main_plan=_main_plan("DataExpertAgent"),
        expert_plan=_expert_plan(
            "DataQuestionWorker",
            "answer_financial_metric",
            worker_inputs=_roe_worker_inputs("中国平安最近 ROE 怎么样？"),
        ),
        answers=(),
    )
    service = AgentRuntimeService(
        context_store=MemoryAgentContextStore(),
        context_repository=MemoryContextRepository(),
        dashboard_services=_dashboard_services(),
        llm_provider_factory=lambda: llm_provider,
        warehouse_repository=None,
    )

    result = service.run_user_qna(
        UserQnaCommand(
            run_id="ar_qna_hidden_data_worker",
            scope_version_id="scope-1",
            message="中国平安最近 ROE 怎么样？",
            universe="ALL_A",
            language="zh",
            conversation_context=(),
        )
    )

    assert llm_provider.calls == ["main_plan"]
    assert result.global_plan.domain_tasks == ()
    assert result.trace_steps == ()
    assert result.global_plan.planner_messages[0]["kind"] == "blocked"
    assert "当前环境没有开放该能力" in result.answer


def test_v1_user_qna_service_replans_when_worker_is_blocked() -> None:
    """Hidden domain output should be blocked before ExpertAgent execution."""
    llm_provider = _SequencedLLMProvider(
        main_plan=_main_plan("DataExpertAgent"),
        expert_plan=_expert_plan(
            "DataQuestionWorker",
            "answer_financial_metric",
            worker_inputs=_roe_worker_inputs("中国平安最近 ROE 怎么样？"),
        ),
        answers=(),
    )
    service = AgentRuntimeService(
        context_store=MemoryAgentContextStore(),
        context_repository=MemoryContextRepository(),
        dashboard_services=_dashboard_services(),
        llm_provider_factory=lambda: llm_provider,
        warehouse_repository=None,
    )

    result = service.run_user_qna(
        UserQnaCommand(
            run_id="ar_qna_blocked_worker",
            scope_version_id="scope-1",
            message="中国平安最近 ROE 怎么样？",
            universe="ALL_A",
            language="zh",
            conversation_context=(),
        )
    )

    assert llm_provider.calls == ["main_plan"]
    assert result.global_plan.domain_tasks == ()
    assert result.trace_steps == ()
    assert result.final_answer.limitations == ("requested_capability_not_executable",)
    assert "当前环境没有开放该能力" in result.answer


def test_v1_user_qna_service_derives_metric_inputs_from_current_turn() -> None:
    """DataQuestionWorker should derive lookup keys from current user text."""
    llm_provider = _SequencedLLMProvider(
        main_plan=_main_plan("DataExpertAgent"),
        expert_plan=_expert_plan("DataQuestionWorker", "answer_financial_metric"),
        answers=(),
    )
    service = AgentRuntimeService(
        context_store=MemoryAgentContextStore(),
        context_repository=MemoryContextRepository(),
        dashboard_services=_dashboard_services(),
        llm_provider_factory=lambda: llm_provider,
        warehouse_repository=_FinancialMetricWarehouse(),
    )

    result = service.run_user_qna(
        UserQnaCommand(
            run_id="ar_qna_missing_worker_inputs",
            scope_version_id="scope-1",
            message="看一下中国平安的 ROE",
            universe="ALL_A",
            language="zh",
            conversation_context=(),
        )
    )

    assert llm_provider.calls == ["main_plan", "expert_plan"]
    assert result.trace_steps[0].status is AgentExecutionStatus.SUCCEEDED
    assert "中国平安" in result.answer
    assert "ROE TTM" in result.answer


def test_v1_user_qna_service_replans_when_worker_artifacts_fail_audit() -> None:
    """Missing required worker artifacts should be treated as bad output and replanned."""
    llm_provider = _SequencedLLMProvider(
        main_plan=_main_plan("GeneralQnaExpertAgent"),
        expert_plan=_expert_plan(
            "GeneralQnaWorker",
            "answer_general_qna",
            required_output_types=("qna_answer", "evidence_package"),
        ),
        answers=("只有普通回答，没有证据包。", "再次普通回答，仍没有证据包。"),
    )
    service = AgentRuntimeService(
        context_store=MemoryAgentContextStore(),
        context_repository=MemoryContextRepository(),
        dashboard_services=_dashboard_services(),
        llm_provider_factory=lambda: llm_provider,
    )

    result = service.run_user_qna(
        UserQnaCommand(
            run_id="ar_qna_bad_artifacts",
            scope_version_id="scope-1",
            message="给我带证据包的回答",
            universe="ALL_A",
            language="zh",
            conversation_context=(),
        )
    )

    assert llm_provider.calls == ["main_plan", "expert_plan", "answer", "expert_plan", "answer"]
    assert any("missing_required_artifacts" in prompt for prompt in llm_provider.prompts)
    assert result.trace_steps[0].status is AgentExecutionStatus.BLOCKED
    assert "missing required artifacts" in result.answer


def test_dashboard_query_error_surfaces_safe_error_code() -> None:
    """Dashboard errors should be visible as status, not collapsed to empty rows."""
    llm_provider = _SequencedLLMProvider(
        main_plan=_main_plan("GeneralQnaExpertAgent"),
        expert_plan=_expert_plan("GeneralQnaWorker", "answer_general_qna"),
        answers=("Dashboard 候选源暂时不可用。",),
    )
    service = AgentRuntimeService(
        context_store=MemoryAgentContextStore(),
        context_repository=MemoryContextRepository(),
        dashboard_services=_exploding_dashboard_services(),
        llm_provider_factory=lambda: llm_provider,
    )

    result = service.run_user_qna(
        UserQnaCommand(
            run_id="ar_qna_dashboard_error",
            scope_version_id="scope-1",
            message="今日研究候选有哪些？",
            universe="ALL_A",
            language="zh",
            conversation_context=(),
        )
    )

    table = next(
        artifact for artifact in result.artifacts if artifact.artifact_type == "analysis_table"
    )

    assert table.payload_json["status"] == "error"
    assert table.payload_json["error_code"] == "RuntimeError"
    assert "dashboard_candidates" in llm_provider.prompts[-1]
    assert "RuntimeError" in llm_provider.prompts[-1]


def _dashboard_services() -> DashboardServiceBundle:
    """Return an in-memory dashboard bundle with one candidate."""
    repository = MemoryDashboardRepository()
    run = ResearchRun(
        run_id="run-1",
        decision_at=DECISION_AT,
        strategy_id="strategy-1",
        version_id="scope-1",
        universe=["000001.SZ"],
        status="partial",
        item_count=1,
        published_count=1,
    )
    item = ResearchItem(
        item_id="item-1",
        run_id=run.run_id,
        symbol="000001.SZ",
        signal_type="research_candidate",
        confidence=0.82,
        statement="经营现金流改善",
        workflow_run_id="wf-1",
        snapshot_id="assess-old",
        status="published",
    )
    repository.add_run(run)
    repository.add_items([item])
    return DashboardServiceBundle.in_memory(dashboard_repository=repository)


def _exploding_dashboard_services() -> object:
    return SimpleNamespace(
        query=_ExplodingDashboardQuery(),
        providers=SimpleNamespace(list_status=lambda: []),
    )


class _ExplodingDashboardQuery:
    def list_research_candidates_v2(self, **_kwargs: object) -> object:
        raise RuntimeError("dashboard down")


def _main_plan(agent_name: str, *, task: str = "Delegate to the selected ExpertAgent.") -> dict:
    """Return one deterministic MainAgent plan."""
    return {
        "steps": [
            {
                "step_id": "s1",
                "agent": agent_name,
                "task": task,
                "required_output_types": ["qna_answer", "analysis_table"],
            }
        ],
        "final_answer_requirements": ["use_approved_capsules_only"],
    }


def _expert_plan(
    worker_agent: str,
    skill_id: str,
    *,
    task: str = "Execute the selected worker skill.",
    required_output_types: tuple[str, ...] = ("qna_answer", "analysis_table"),
    worker_inputs: dict[str, str] | None = None,
) -> dict:
    """Return one deterministic ExpertAgent worker plan."""
    return {
        "steps": [
            {
                "step_id": "w1",
                "worker_agent": worker_agent,
                "skill_id": skill_id,
                "task": task,
                "required_output_types": list(required_output_types),
                "constraints": {"worker_inputs": worker_inputs} if worker_inputs else {},
            }
        ],
        "audit_requirements": ["verify_artifacts_before_returning"],
    }


def _roe_worker_inputs(user_query: str, *, chart_type: str = "line") -> dict[str, str]:
    """Return ExpertAgent-filled worker placeholders for a ROE task."""
    return {
        "user_query": user_query,
        "security_query": "中国平安",
        "indicator_id": "roe_ttm",
        "chart_type": chart_type,
    }


class _SequencedLLMProvider(DeterministicLLMProvider):
    """Test LLM that returns Main plan, Expert plan, then optional answers."""

    def __init__(
        self,
        *,
        main_plan: dict,
        expert_plan: dict | tuple[dict, ...],
        answers: tuple[str, ...],
    ) -> None:
        """Initialize the deterministic provider with ordered outputs."""
        super().__init__(response={})
        self._main_plan = main_plan
        self._expert_plans = (
            list(expert_plan) if isinstance(expert_plan, tuple) else [expert_plan]
        )
        self._expert_plan_fallback = self._expert_plans[-1]
        self._answers = list(answers)
        self.calls: list[str] = []
        self.prompts: list[str] = []
        self._structured_calls = 0

    def complete(
        self,
        prompt: str,
        *,
        response_schema: dict[str, object] | None = None,
        temperature: float = 0.0,
    ) -> LLMResult:
        """Return deterministic structured plans or user answers in order."""
        del temperature
        self.prompts.append(prompt)
        if response_schema is not None:
            self._structured_calls += 1
            if self._structured_calls == 1:
                self.calls.append("main_plan")
                return LLMResult(
                    output=self._main_plan,
                    model="test",
                    success=True,
                    latency_ms=0.0,
                    raw_response=str(self._main_plan),
                )
            self.calls.append("expert_plan")
            expert_plan = (
                self._expert_plans.pop(0)
                if self._expert_plans
                else self._expert_plan_fallback
            )
            return LLMResult(
                output=expert_plan,
                model="test",
                success=True,
                latency_ms=0.0,
                raw_response="expert_plan",
            )
        if not self._answers:
            raise AssertionError("unexpected free-form answer call")
        self.calls.append("answer")
        answer = self._answers.pop(0)
        return LLMResult(
            output={"content": answer},
            model="test",
            success=True,
            latency_ms=0.0,
            raw_response=answer,
        )


class _FinancialMetricWarehouse:
    """Fake PIT warehouse for financial-metric Q&A tests."""

    def __init__(self) -> None:
        """Initialize the captured query list."""
        self.indicator_queries = []
        self.security_queries = []

    def search_security_profiles(
        self,
        query: object,
    ) -> list[SecurityProfileValue]:
        """Resolve the Chinese company name to an active security profile."""
        self.security_queries.append(getattr(query, "query_text", ""))
        return [
            SecurityProfileValue(
                security_id="601318.SH",
                symbol="601318",
                name="中国平安",
                exchange="SH",
                listed_at=date(2007, 3, 1),
                delisted_at=None,
                is_st=False,
            )
        ]

    def discover_indicators(
        self,
        *,
        security_ids: tuple[str, ...],
        query_text: str,
        decision_at: datetime,
        limit: int,
    ) -> list[dict[str, object]]:
        """Return warehouse-discovered ROE metadata for service tests."""
        del security_ids, query_text, decision_at, limit
        return [
            {
                "indicator_id": "roe_ttm",
                "label": "ROE TTM",
                "unit": "%",
                "value_scale": 100,
                "aliases": ["roe", "ROE", "净资产收益率"],
                "coverage": {"point_count": 2},
                "source_fields": ["fina_indicator.roe"],
            }
        ]

    def indicator_history(
        self,
        query: object,
    ) -> list[IndicatorHistoryValue]:
        """Return PIT-safe ROE history."""
        self.indicator_queries.append(query)
        return [
            IndicatorHistoryValue(
                fact_id="fact_roe_2023",
                provider="tushare",
                security_id="601318.SH",
                indicator_id="roe_ttm",
                event_at=datetime(2023, 12, 31, tzinfo=UTC),
                available_at=datetime(2024, 3, 22, tzinfo=UTC),
                fetched_at=datetime(2024, 3, 23, tzinfo=UTC),
                numeric_value=Decimal("0.101"),
                quality_score=Decimal("0.99"),
            ),
            IndicatorHistoryValue(
                fact_id="fact_roe_2024",
                provider="tushare",
                security_id="601318.SH",
                indicator_id="roe_ttm",
                event_at=datetime(2024, 12, 31, tzinfo=UTC),
                available_at=datetime(2025, 3, 22, tzinfo=UTC),
                fetched_at=datetime(2025, 3, 23, tzinfo=UTC),
                numeric_value=Decimal("0.123"),
                quality_score=Decimal("0.99"),
            ),
        ]
