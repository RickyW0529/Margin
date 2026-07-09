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
from margin.agents.tools.gateway import InMemoryToolRateLimiter, ToolGateway
from margin.agents.tools.langgraph_adapter import LangGraphRuntimeContext, LangGraphToolAdapter
from margin.agents.tools.schema_registry import InMemoryToolSchemaRegistry
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
        expires_at=datetime(2099, 1, 1, tzinfo=UTC),
        max_tool_calls=4,
        max_result_bytes=512,
    )


def _spec(
    *,
    max_output_bytes: int = 512,
    idempotent: bool = True,
    returns_raw_payload: bool = False,
) -> ToolSpec:
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
        idempotent=idempotent,
        mutates_state=False,
        timeout_ms=1000,
        max_output_bytes=max_output_bytes,
        returns_raw_payload=returns_raw_payload,
        allowed_runtimes=("deterministic", "langgraph"),
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


def test_tool_gateway_blocks_expired_capability() -> None:
    """Expired capability tokens must not execute tools."""
    catalog = ToolCatalog()
    catalog.register(_spec(), lambda request: {"message": request.input_json["message"]})
    gateway = ToolGateway(catalog=catalog, audit_store=InMemoryToolAuditStore())
    token = _token()
    expired = token.model_copy(update={"expires_at": datetime(2000, 1, 1, tzinfo=UTC)})

    result = gateway.call(_request(token=expired))

    assert result.status is ToolCallStatus.BLOCKED
    assert result.error_code == "capability_expired"


def test_tool_gateway_blocks_max_tool_calls() -> None:
    """Per-token max_tool_calls is enforced across successive calls."""
    catalog = ToolCatalog()
    catalog.register(_spec(), lambda request: {"message": request.input_json["message"]})
    gateway = ToolGateway(catalog=catalog, audit_store=InMemoryToolAuditStore())
    token = _token().model_copy(update={"max_tool_calls": 1})

    first = gateway.call(_request(idempotency_key="call-1", token=token))
    second = gateway.call(_request(idempotency_key="call-2", token=token))

    assert first.status is ToolCallStatus.SUCCEEDED
    assert second.status is ToolCallStatus.BLOCKED
    assert second.error_code == "max_tool_calls_exceeded"


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
            "raw_text": "raw provider payload",
        },
    )
    gateway = ToolGateway(catalog=catalog, audit_store=audit_store)

    result = gateway.call(_request())

    assert result.status is ToolCallStatus.SUCCEEDED
    assert result.output_json == {
        "message": "hello",
        "provider_token": "[redacted]",
        "raw_text": "[redacted]",
    }
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


def test_tool_gateway_does_not_replay_non_idempotent_call() -> None:
    """Non-idempotent tools must execute again even with the same idempotency key."""
    calls = {"count": 0}
    catalog = ToolCatalog()

    def handler(request):
        calls["count"] += 1
        return {"message": request.input_json["message"], "count": calls["count"]}

    catalog.register(_spec(idempotent=False), handler)
    gateway = ToolGateway(catalog=catalog, audit_store=InMemoryToolAuditStore())

    first = gateway.call(_request(idempotency_key="non-idem"))
    second = gateway.call(_request(idempotency_key="non-idem"))

    assert first.output_json != second.output_json
    assert calls["count"] == 2


def test_tool_gateway_validates_input_and_output_schema_refs() -> None:
    """ToolGateway should block calls that do not match registered schema refs."""
    calls = {"count": 0}
    catalog = ToolCatalog()
    catalog.register(_spec(), lambda _request: calls.update(count=calls["count"] + 1) or {})
    schema_registry = InMemoryToolSchemaRegistry()
    schema_registry.register_required_keys("schema.context.echo.input", ("message",))
    schema_registry.register_required_keys("schema.context.echo.output", ("message",))
    gateway = ToolGateway(
        catalog=catalog,
        audit_store=InMemoryToolAuditStore(),
        schema_registry=schema_registry,
    )

    input_result = gateway.call(_request(input_json={"missing": "message"}))
    output_result = gateway.call(_request(idempotency_key="bad-output"))

    assert input_result.status is ToolCallStatus.BLOCKED
    assert input_result.error_code == "input_schema_invalid"
    assert output_result.status is ToolCallStatus.BLOCKED
    assert output_result.error_code == "output_schema_invalid"
    assert calls["count"] == 1


def test_tool_gateway_blocks_raw_payload_tool_specs() -> None:
    """Registered tools may not declare raw payload returns through Agent Gateway."""
    catalog = ToolCatalog()
    catalog.register(_spec(returns_raw_payload=True), lambda _request: {"raw_text": "raw"})
    gateway = ToolGateway(catalog=catalog, audit_store=InMemoryToolAuditStore())

    result = gateway.call(_request())

    assert result.status is ToolCallStatus.BLOCKED
    assert result.error_code == "raw_payload_tool_forbidden"


def test_tool_gateway_blocks_rate_limited_calls() -> None:
    """ToolGateway should enforce per-tool rate-limit buckets before execution."""
    calls = {"count": 0}
    catalog = ToolCatalog()
    catalog.register(
        _spec(idempotent=False),
        lambda request: calls.update(count=calls["count"] + 1)
        or {"message": request.input_json["message"]},
    )
    gateway = ToolGateway(
        catalog=catalog,
        audit_store=InMemoryToolAuditStore(),
        rate_limiter=InMemoryToolRateLimiter(limit_per_tool=1),
    )

    first = gateway.call(_request(idempotency_key="rate-1"))
    second = gateway.call(_request(idempotency_key="rate-2"))

    assert first.status is ToolCallStatus.SUCCEEDED
    assert second.status is ToolCallStatus.BLOCKED
    assert second.error_code == "rate_limited"
    assert calls["count"] == 1


def test_sandbox_tool_requires_sandbox_policy_and_redacts_secrets() -> None:
    """Sandbox tools require explicit sandbox scope and still redact secret output."""
    sandbox_spec = ToolSpec(
        tool_name="sandbox.python",
        tool_version="v1",
        description="Run restricted sandbox snippets.",
        owner_domain="code_execution",
        input_schema_ref="schema.sandbox.input",
        output_schema_ref="schema.sandbox.output",
        required_data_access=(DataAccessPolicy.NO_DATA,),
        required_write_policy=(ProductionWritePolicy.WRITE_CONTEXT_ONLY,),
        required_tool_policy=(ToolPolicy.SANDBOX_TOOLS,),
        idempotent=False,
        mutates_state=False,
        timeout_ms=1000,
        max_output_bytes=512,
        returns_raw_payload=False,
        allowed_runtimes=("sandbox",),
    )
    catalog = ToolCatalog()
    catalog.register(
        sandbox_spec,
        lambda _request: {
            "stdout": "ok",
            "provider_token": "must-not-leak",
            "raw_payload": "hidden",
        },
    )
    gateway = ToolGateway(catalog=catalog, audit_store=InMemoryToolAuditStore())

    denied = gateway.call(_request(tool_name="sandbox.python", idempotency_key="sandbox-denied"))
    allowed = gateway.call(
        _request(
            tool_name="sandbox.python",
            idempotency_key="sandbox-allowed",
            token=_token(
                data_access=(DataAccessPolicy.NO_DATA,),
                tool_policy=(ToolPolicy.SANDBOX_TOOLS,),
                allowed_tool_names=("sandbox.python",),
            ),
        )
    )

    assert denied.status is ToolCallStatus.BLOCKED
    assert denied.error_code == "capability_denied"
    assert allowed.status is ToolCallStatus.SUCCEEDED
    assert allowed.output_json == {
        "stdout": "ok",
        "provider_token": "[redacted]",
        "raw_payload": "[redacted]",
    }


def test_langgraph_tool_adapter_uses_gateway_only() -> None:
    """LangGraph-facing adapter must call ToolGateway only.

    Returns:
        None: .
    """
    catalog = ToolCatalog()
    catalog.register(_spec(), lambda request: {"message": request.input_json["message"]})
    gateway = ToolGateway(catalog=catalog, audit_store=InMemoryToolAuditStore())
    adapter = LangGraphToolAdapter(tool_spec=_spec(), gateway=gateway)

    result = adapter.invoke(
        {"message": "from langgraph"},
        LangGraphRuntimeContext(
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
    assert result.output_json == {"message": "from langgraph"}
