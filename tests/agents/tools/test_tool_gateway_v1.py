"""test_tool_gateway_v1 module."""

from __future__ import annotations

from datetime import UTC, datetime

from margin.agents.security.capability import CapabilityToken
from margin.agents.security.policies import (
    DataAccessPolicy,
    ProductionWritePolicy,
    ToolPolicy,
)
from margin.agents.tools.audit import InMemoryToolAuditStore
from margin.agents.tools.catalog import ToolCatalog
from margin.agents.tools.gateway import ToolGateway
from margin.agents.tools.langchain_adapter import LangChainRuntimeContext, LangChainToolAdapter
from margin.agents.tools.specs import ToolCallRequest, ToolCallStatus, ToolSpec


def _token(
    *,
    data_access: tuple[DataAccessPolicy, ...] = (DataAccessPolicy.READ_ANALYSIS_MART,),
    production_write: tuple[ProductionWritePolicy, ...] = (
        ProductionWritePolicy.WRITE_CONTEXT_ONLY,
    ),
    tool_policy: tuple[ToolPolicy, ...] = (ToolPolicy.READ_ONLY_TOOLS,),
    allowed_tool_names: tuple[str, ...] = ("context.echo",),
) -> CapabilityToken:
    """Helper token.

    Args:
        data_access: tuple[DataAccessPolicy, ...]: .
        production_write: tuple[ProductionWritePolicy, ...]: .
        tool_policy: tuple[ToolPolicy, ...]: .
        allowed_tool_names: tuple[str, ...]: .

    Returns:
        CapabilityToken: .
    """
    return CapabilityToken(
        token_id="cap_tool",
        run_id="run_tool",
        issued_by="DomainExpert",
        issued_to="EchoWorker",
        domain="general",
        data_access=data_access,
        production_write=production_write,
        tool_policy=tool_policy,
        allowed_artifact_types=("tool_result",),
        allowed_tool_names=allowed_tool_names,
        expires_at=datetime(2026, 7, 9, tzinfo=UTC),
        max_tool_calls=4,
        max_result_bytes=512,
    )


def _spec(*, max_output_bytes: int = 512) -> ToolSpec:
    """Execute _spec logic.

    Args:
        max_output_bytes: int: .

    Returns:
        ToolSpec: .
    """
    return ToolSpec(
        tool_name="context.echo",
        tool_version="v1",
        description="Echo safe context payloads.",
        owner_domain="context",
        input_schema_ref="schema.context.echo.input",
        output_schema_ref="schema.context.echo.output",
        required_data_access=(DataAccessPolicy.READ_ANALYSIS_MART,),
        required_write_policy=(ProductionWritePolicy.WRITE_CONTEXT_ONLY,),
        required_tool_policy=(ToolPolicy.READ_ONLY_TOOLS,),
        idempotent=True,
        mutates_state=False,
        timeout_ms=1000,
        max_output_bytes=max_output_bytes,
        returns_raw_payload=False,
        allowed_runtimes=("deterministic", "langchain"),
    )


def _request(
    *,
    tool_name: str = "context.echo",
    input_json: dict | None = None,
    idempotency_key: str = "idem-tool",
    token: CapabilityToken | None = None,
) -> ToolCallRequest:
    """Helper request.

    Args:
        tool_name: str: .
        input_json: dict | None: .
        idempotency_key: str: .
        token: CapabilityToken | None: .

    Returns:
        ToolCallRequest: .
    """
    return ToolCallRequest(
        tool_call_id=f"tc_{idempotency_key}",
        run_id="run_tool",
        task_id="wt_echo",
        caller_agent="EchoWorker",
        tool_name=tool_name,
        tool_version="v1",
        input_json=input_json or {"message": "hello"},
        capability_token=token or _token(),
        context_pack_id="ctx_tool",
        idempotency_key=idempotency_key,
        deadline_ms=1000,
    )


def test_tool_gateway_blocks_unregistered_tool() -> None:
    """test_tool_gateway_blocks_unregistered_tool implementation.

    Returns:
        None: .
    """
    gateway = ToolGateway(catalog=ToolCatalog(), audit_store=InMemoryToolAuditStore())

    result = gateway.call(_request())

    assert result.status is ToolCallStatus.BLOCKED
    assert result.error_code == "tool_not_registered"


def test_tool_gateway_blocks_missing_capability() -> None:
    """test_tool_gateway_blocks_missing_capability implementation.

    Returns:
        None: .
    """
    catalog = ToolCatalog()
    catalog.register(_spec(), lambda request: {"message": request.input_json["message"]})
    gateway = ToolGateway(catalog=catalog, audit_store=InMemoryToolAuditStore())
    token = _token(tool_policy=(ToolPolicy.NO_TOOLS,))

    result = gateway.call(_request(token=token))

    assert result.status is ToolCallStatus.BLOCKED
    assert result.error_code == "capability_denied"


def test_tool_gateway_audits_and_redacts_every_call() -> None:
    """test_tool_gateway_audits_and_redacts_every_call implementation.

    Returns:
        None: .
    """
    audit_store = InMemoryToolAuditStore()
    catalog = ToolCatalog()
    catalog.register(
        _spec(),
        lambda request: {
            "message": request.input_json["message"],
            "provider_token": "secret-token",
        },
    )
    gateway = ToolGateway(catalog=catalog, audit_store=audit_store)

    result = gateway.call(_request())

    assert result.status is ToolCallStatus.SUCCEEDED
    assert result.output_json == {"message": "hello", "provider_token": "[redacted]"}
    assert result.audit_ref in audit_store.records
    assert audit_store.records[result.audit_ref].input_redacted_json == {"message": "hello"}


def test_tool_gateway_blocks_output_size_limit() -> None:
    """test_tool_gateway_blocks_output_size_limit implementation.

    Returns:
        None: .
    """
    catalog = ToolCatalog()
    catalog.register(_spec(max_output_bytes=16), lambda _request: {"message": "x" * 200})
    gateway = ToolGateway(catalog=catalog, audit_store=InMemoryToolAuditStore())

    result = gateway.call(_request())

    assert result.status is ToolCallStatus.BLOCKED
    assert result.error_code == "tool_output_too_large"


def test_tool_gateway_replays_idempotent_call_without_reexecuting() -> None:
    """test_tool_gateway_replays_idempotent_call_without_reexecuting implementation.

    Returns:
        None: .
    """
    calls = {"count": 0}
    catalog = ToolCatalog()

    def handler(request):
        """Process handler.

        Args:
            request: Any: .

        Returns:
            Any: .
        """
        calls["count"] += 1
        return {"message": request.input_json["message"], "count": calls["count"]}

    catalog.register(_spec(), handler)
    gateway = ToolGateway(catalog=catalog, audit_store=InMemoryToolAuditStore())

    first = gateway.call(_request(idempotency_key="same"))
    second = gateway.call(_request(idempotency_key="same"))

    assert first.output_json == second.output_json
    assert calls["count"] == 1


def test_langchain_tool_adapter_uses_gateway_only() -> None:
    """test_langchain_tool_adapter_uses_gateway_only implementation.

    Returns:
        None: .
    """
    catalog = ToolCatalog()
    catalog.register(_spec(), lambda request: {"message": request.input_json["message"]})
    gateway = ToolGateway(catalog=catalog, audit_store=InMemoryToolAuditStore())
    adapter = LangChainToolAdapter(tool_spec=_spec(), gateway=gateway)

    result = adapter.invoke(
        {"message": "from langchain"},
        LangChainRuntimeContext(
            run_id="run_tool",
            worker_task_id="wt_echo",
            worker_agent="EchoWorker",
            capability_token=_token(),
            context_pack_id="ctx_tool",
            idempotency_key="lc",
            deadline_ms=1000,
        ),
    )

    assert result.status is ToolCallStatus.SUCCEEDED
    assert result.output_json == {"message": "from langchain"}
