"""Persistence tests for ToolGateway audit tables."""

from __future__ import annotations

from datetime import UTC, datetime

from margin.agents.security.capability import CapabilityToken
from margin.agents.security.policies import (
    DataAccessPolicy,
    ProductionWritePolicy,
    ToolPolicy,
)
from margin.agents.tools.audit import SQLAlchemyToolAuditStore
from margin.agents.tools.specs import ToolCallRequest, ToolCallStatus
from margin.storage.base import Base
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)


def test_sqlalchemy_tool_audit_store_round_trips_redacted_records(
    database_url: str,
) -> None:
    """SQLAlchemyToolAuditStore persists safe call/result audit records."""
    engine = create_database_engine(DatabaseSettings(url=database_url))
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS tool")
    Base.metadata.create_all(engine)
    store = SQLAlchemyToolAuditStore(create_session_factory(engine))
    request = ToolCallRequest(
        tool_call_id="tc_sql_tool",
        run_id="run_tool_sql",
        task_id="wt_tool_sql",
        caller_agent="ToolWorker",
        tool_name="context.echo",
        tool_version="v1",
        input_json={"message": "hello", "provider_token": "secret"},
        capability_token=_token(),
        idempotency_key="idem-sql-tool",
        deadline_ms=1000,
    )

    record = store.write(
        request=request,
        status=ToolCallStatus.SUCCEEDED,
        input_redacted_json={"message": "hello", "provider_token": "[redacted]"},
        output_redacted_json={"message": "hello"},
        error_code=None,
    )
    store.write(
        request=request,
        status=ToolCallStatus.SUCCEEDED,
        input_redacted_json={"message": "hello", "provider_token": "[redacted]"},
        output_redacted_json={"message": "hello"},
        error_code=None,
    )

    stored = store.get_record(record.audit_ref)
    assert stored == record
    assert stored is not None
    assert stored.input_redacted_json["provider_token"] == "[redacted]"
    assert stored.output_hash is not None


def _token() -> CapabilityToken:
    """Return a deterministic capability token."""
    return CapabilityToken(
        token_id="cap_tool_sql",
        run_id="run_tool_sql",
        issued_by="DomainExpert",
        issued_to="ToolWorker",
        domain="general",
        data_access=(DataAccessPolicy.READ_ANALYSIS_MART,),
        production_write=(ProductionWritePolicy.WRITE_CONTEXT_ONLY,),
        tool_policy=(ToolPolicy.READ_ONLY_TOOLS,),
        allowed_artifact_types=("tool_result",),
        allowed_tool_names=("context.echo",),
        expires_at=datetime(2026, 7, 9, tzinfo=UTC),
        max_tool_calls=4,
        max_result_bytes=512,
    )
