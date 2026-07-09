"""Safe ToolGateway audit API routes."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from margin.agents.tools.audit import InMemoryToolAuditStore
from margin.api.dependencies import get_tool_audit_store

router = APIRouter(prefix="/api/v1", tags=["tool-audit"])

ToolAuditStore = Annotated[InMemoryToolAuditStore, Depends(get_tool_audit_store)]


class ToolCallAuditResponse(BaseModel):
    """Safe redacted tool-call audit response.."""

    audit_ref: str
    tool_call_id: str
    run_id: str
    task_id: str
    caller_agent: str
    tool_name: str
    tool_version: str
    input_hash: str
    input_redacted_json: dict[str, Any]
    output_hash: str | None
    output_redacted_json: dict[str, Any] | None
    status: str
    error_code: str | None
    started_at: datetime
    finished_at: datetime


@router.get("/tool-calls/{audit_ref}", response_model=ToolCallAuditResponse)
def get_tool_call_audit(
    audit_ref: str,
    audit_store: ToolAuditStore,
) -> ToolCallAuditResponse:
    """Return one redacted ToolGateway audit record.

    Args:
        audit_ref: str: .
        audit_store: ToolAuditStore: .

    Returns:
        ToolCallAuditResponse: .
    """
    record = audit_store.records.get(audit_ref)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "tool_call_audit_not_found",
                "message": "tool call audit not found",
            },
        )
    return ToolCallAuditResponse(
        audit_ref=record.audit_ref,
        tool_call_id=record.tool_call_id,
        run_id=record.run_id,
        task_id=record.task_id,
        caller_agent=record.caller_agent,
        tool_name=record.tool_name,
        tool_version=record.tool_version,
        input_hash=record.input_hash,
        input_redacted_json=record.input_redacted_json,
        output_hash=record.output_hash,
        output_redacted_json=record.output_redacted_json,
        status=record.status.value,
        error_code=record.error_code,
        started_at=record.started_at,
        finished_at=record.finished_at,
    )
