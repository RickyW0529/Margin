"""Tests for Agent runtime capability visibility."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from margin.agents.cards.registry import (
    default_domain_agent_cards,
    default_worker_agent_cards,
)
from margin.agents.runtime.capability_registry import (
    CapabilityRegistry,
    CapabilityStatus,
)
from margin.agents.runtime.executor_registry import ExecutorRegistry, ExecutorSpec
from margin.agents.security.capability import CapabilityToken
from margin.agents.security.policies import (
    DataAccessPolicy,
    ProductionWritePolicy,
    ToolPolicy,
)
from margin.agents.tools.catalog import ToolCatalog
from margin.agents.tools.specs import ToolCallRequest, ToolSpec

_WAREHOUSE_TOOLS = (
    "warehouse.describe_schema",
    "warehouse.resolve_security",
    "warehouse.discover_indicators",
    "warehouse.query_indicator_history",
)
_DASHBOARD_TOOLS = ("dashboard.read_candidates",)
_WORKSPACE_TOOLS = (
    "workspace.list_files",
    "workspace.read_file",
    "workspace.search",
    "workspace.write_file",
    "workspace.run_command",
)
_ALL_TOOLS = (*_WAREHOUSE_TOOLS, *_DASHBOARD_TOOLS)


def test_domain_without_executable_worker_is_hidden_from_main_planner() -> None:
    """Main planner should only see domains backed by executable worker skills."""
    registry = _capability_registry(
        executor_registry=_executor_registry(include_data=True, include_general=True),
        tool_catalog=_tool_catalog(*_ALL_TOOLS),
    )

    visible = registry.visible_domain_cards(capability_token=_token())

    visible_names = {card.name for card in visible}
    assert visible_names == {"DataExpertAgent", "GeneralQnaExpertAgent"}
    assert "QuantExpertAgent" not in visible_names
    assert "EvidenceRagExpertAgent" not in visible_names


def test_worker_skill_without_executor_is_hidden_from_expert_planner() -> None:
    """Worker cards with no executor should not reach ExpertAgent planning."""
    registry = _capability_registry(tool_catalog=_tool_catalog(*_WAREHOUSE_TOOLS))

    visible = registry.visible_worker_cards(domain="data", capability_token=_token())

    assert visible == ()


def test_worker_skill_with_missing_tool_is_hidden() -> None:
    """A worker with an executor but missing allowlisted tools is not executable."""
    registry = _capability_registry(
        executor_registry=_executor_registry(include_data=True),
        tool_catalog=ToolCatalog(),
    )

    visible = registry.visible_worker_cards(domain="data", capability_token=_token())
    snapshot = registry.snapshot(capability_token=_token())
    data_worker = next(
        view for view in snapshot.workers if view.worker_agent == "DataQuestionWorker"
    )

    assert visible == ()
    assert data_worker.status is CapabilityStatus.MISSING_TOOL


def test_tool_denied_by_capability_token_is_hidden() -> None:
    """Tool allowlists must also pass capability-token checks."""
    registry = _capability_registry(
        executor_registry=_executor_registry(include_data=True),
        tool_catalog=_tool_catalog(*_WAREHOUSE_TOOLS),
    )
    denied_token = _token(allowed_tool_names=())

    visible = registry.visible_worker_cards(domain="data", capability_token=denied_token)
    snapshot = registry.snapshot(capability_token=denied_token)
    data_worker = next(
        view for view in snapshot.workers if view.worker_agent == "DataQuestionWorker"
    )

    assert visible == ()
    assert data_worker.status is CapabilityStatus.TOKEN_DENIED


def test_default_card_output_contracts_are_consistent_for_executable_domains() -> None:
    """All executable default card outputs should be producible by their workers."""
    registry = _capability_registry(
        executor_registry=_executor_registry(
            include_data=True,
            include_general=True,
            include_code=True,
        ),
        tool_catalog=_tool_catalog(*_ALL_TOOLS, *_WORKSPACE_TOOLS),
    )

    report = registry.validate_startup_contracts()

    assert report.valid is True
    assert report.errors == ()


def test_startup_contracts_fail_on_missing_executor_for_visible_skill() -> None:
    """Startup validation should report non-planned worker skills with no executor."""
    registry = _capability_registry(tool_catalog=_tool_catalog(*_WAREHOUSE_TOOLS))

    report = registry.validate_startup_contracts()

    assert report.valid is False
    assert any(
        "missing executor for DataQuestionWorker.answer_financial_metric" in error
        for error in report.errors
    )
    assert any(
        "missing executor for GeneralQnaWorker.answer_general_qna" in error
        for error in report.errors
    )


def test_capability_snapshot_explains_hidden_quant_domain() -> None:
    """Snapshot should preserve why non-executable domains are hidden."""
    registry = _capability_registry(
        executor_registry=_executor_registry(include_data=True, include_general=True),
        tool_catalog=_tool_catalog(*_ALL_TOOLS),
    )

    snapshot = registry.snapshot(capability_token=_token())
    quant = next(view for view in snapshot.domains if view.domain_agent == "QuantExpertAgent")

    assert quant.status is CapabilityStatus.MISSING_EXECUTOR
    assert "no worker cards registered" in quant.reason


def test_capability_snapshot_lists_executable_data_worker_and_tools() -> None:
    """Snapshot should list executable data worker and allowed tools."""
    registry = _capability_registry(
        executor_registry=_executor_registry(include_data=True, include_general=True),
        tool_catalog=_tool_catalog(*_ALL_TOOLS),
    )

    snapshot = registry.snapshot(capability_token=_token())
    data = next(view for view in snapshot.workers if view.worker_agent == "DataQuestionWorker")
    tools = {view.tool_name: view.status for view in snapshot.tools}

    assert data.status is CapabilityStatus.EXECUTABLE
    assert tools["warehouse.describe_schema"] is CapabilityStatus.EXECUTABLE


def _capability_registry(
    *,
    executor_registry: ExecutorRegistry | None = None,
    tool_catalog: ToolCatalog | None = None,
) -> CapabilityRegistry:
    return CapabilityRegistry(
        domain_cards=default_domain_agent_cards(),
        worker_cards=default_worker_agent_cards(),
        executor_registry=executor_registry or ExecutorRegistry(),
        tool_catalog=tool_catalog or ToolCatalog(),
    )


def _executor_registry(
    *,
    include_data: bool = False,
    include_general: bool = False,
    include_code: bool = False,
) -> ExecutorRegistry:
    registry = ExecutorRegistry()
    if include_data:
        registry.register_spec(
            ExecutorSpec(
                agent_name="DataQuestionWorker",
                skill_id="answer_financial_metric",
                executor=object(),
                runtime="langgraph",
                required_tools=_WAREHOUSE_TOOLS,
                output_artifact_types=(
                    "analysis_table",
                    "chart_spec",
                    "computed_metric",
                    "qna_answer",
                    "visualization_image",
                    "worker_activity",
                ),
                domain="data",
            )
        )
    if include_general:
        registry.register_spec(
            ExecutorSpec(
                agent_name="GeneralQnaWorker",
                skill_id="answer_general_qna",
                executor=object(),
                runtime="langgraph",
                required_tools=_DASHBOARD_TOOLS,
                output_artifact_types=("analysis_table", "qna_answer"),
                domain="general",
            )
        )
    if include_code:
        registry.register_spec(
            ExecutorSpec(
                agent_name="CodeWorkspaceWorker",
                skill_id="complete_code_task",
                executor=object(),
                runtime="langgraph",
                required_tools=_WORKSPACE_TOOLS,
                output_artifact_types=(
                    "code_change",
                    "command_result",
                    "qna_answer",
                    "worker_activity",
                ),
                domain="code",
            )
        )
    return registry


def _tool_catalog(*tool_names: str) -> ToolCatalog:
    catalog = ToolCatalog()
    for tool_name in tool_names:
        catalog.register(_tool_spec(tool_name), _noop_handler)
    return catalog


def _tool_spec(tool_name: str) -> ToolSpec:
    data_access = (
        (DataAccessPolicy.READ_DASHBOARD,)
        if tool_name.startswith("dashboard.")
        else (DataAccessPolicy.READ_ANALYSIS_MART,)
    )
    return ToolSpec(
        tool_name=tool_name,
        tool_version="v1",
        description=f"{tool_name} test tool",
        owner_domain="data",
        input_schema_ref=f"{tool_name}.input",
        output_schema_ref=f"{tool_name}.output",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        required_data_access=data_access,
        required_write_policy=(),
        required_tool_policy=(ToolPolicy.READ_ONLY_TOOLS,),
        idempotent=True,
        mutates_state=False,
        timeout_ms=1000,
        max_output_bytes=1024,
        allowed_runtimes=("langgraph",),
    )


def _noop_handler(_request: ToolCallRequest) -> dict[str, object]:
    return {}


def _token(
    *,
    allowed_tool_names: tuple[str, ...] = _ALL_TOOLS,
) -> CapabilityToken:
    return CapabilityToken(
        token_id="cap_test",
        run_id="run_test",
        issued_by="MainAgent",
        issued_to="MainAgent",
        domain="global",
        data_access=(
            DataAccessPolicy.READ_CHAT_SUMMARY,
            DataAccessPolicy.READ_DASHBOARD,
            DataAccessPolicy.READ_ANALYSIS_MART,
            DataAccessPolicy.READ_PROVIDER_STATUS,
        ),
        production_write=(ProductionWritePolicy.WRITE_CONTEXT_ONLY,),
        tool_policy=(ToolPolicy.READ_ONLY_TOOLS, ToolPolicy.DATA_SYNC_TOOLS),
        allowed_artifact_types=(
            "analysis_table",
            "chart_spec",
            "computed_metric",
            "qna_answer",
            "visualization_image",
            "worker_activity",
        ),
        allowed_tool_names=allowed_tool_names,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        max_tool_calls=8,
        max_result_bytes=4096,
        can_delegate=True,
        delegation_depth_remaining=2,
    )
