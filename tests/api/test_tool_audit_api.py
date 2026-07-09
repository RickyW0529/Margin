"""API tests for safe ToolGateway audit views."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from margin.agents.security.capability import CapabilityToken
from margin.agents.security.policies import (
    DataAccessPolicy,
    ProductionWritePolicy,
    ToolPolicy,
)
from margin.agents.tools.audit import InMemoryToolAuditStore
from margin.agents.tools.catalog import ToolCatalog
from margin.agents.tools.gateway import ToolGateway
from margin.agents.tools.specs import ToolCallRequest, ToolSpec
from margin.api.main import create_app


def test_tool_call_audit_api_returns_redacted_record() -> None:
    """test_tool_call_audit_api_returns_redacted_record implementation.

    Returns:
        None: .
    """
    audit_store = InMemoryToolAuditStore()
    catalog = ToolCatalog()
    catalog.register(
        ToolSpec(
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
            max_output_bytes=1024,
        ),
        lambda request: {
            "message": request.input_json["message"],
            "provider_token": "secret-token",
        },
    )
    gateway = ToolGateway(catalog=catalog, audit_store=audit_store)
    gateway.call(
        ToolCallRequest(
            tool_call_id="tc_safe_view",
            run_id="run_tool",
            task_id="task_tool",
            caller_agent="EchoWorker",
            tool_name="context.echo",
            tool_version="v1",
            input_json={"message": "hello", "provider_token": "secret-token"},
            capability_token=_token(),
            idempotency_key="idem-safe-view",
            deadline_ms=1000,
        )
    )
    client = TestClient(create_app(tool_audit_store=audit_store))

    response = client.get("/api/v1/tool-calls/tool_audit_tc_safe_view")

    assert response.status_code == 200
    body = response.json()
    assert body["input_redacted_json"]["provider_token"] == "[redacted]"
    assert body["output_redacted_json"]["provider_token"] == "[redacted]"
    assert "secret-token" not in str(body)


def _token() -> CapabilityToken:
    """_token implementation.

    Returns:
        CapabilityToken: .
    """
    return CapabilityToken(
        token_id="cap_tool",
        run_id="run_tool",
        issued_by="DomainExpert",
        issued_to="EchoWorker",
        domain="general",
        data_access=(DataAccessPolicy.READ_ANALYSIS_MART,),
        production_write=(ProductionWritePolicy.WRITE_CONTEXT_ONLY,),
        tool_policy=(ToolPolicy.READ_ONLY_TOOLS,),
        allowed_artifact_types=("tool_result",),
        allowed_tool_names=("context.echo",),
        expires_at=datetime(2099, 1, 1, tzinfo=UTC),
        max_tool_calls=4,
        max_result_bytes=512,
    )
