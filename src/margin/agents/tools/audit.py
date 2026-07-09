"""ToolGateway audit records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from margin.agent_runtime.context_store import stable_json_hash
from margin.agents.tools.specs import ToolCallRequest, ToolCallStatus


@dataclass(frozen=True)
class ToolAuditRecord:
    """ToolAuditRecord.."""

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
    status: ToolCallStatus
    error_code: str | None
    started_at: datetime
    finished_at: datetime


class InMemoryToolAuditStore:
    """InMemoryToolAuditStore.."""

    def __init__(self) -> None:
        """Init .

        Returns:
            None: .
        """
        self.records: dict[str, ToolAuditRecord] = {}

    def write(
        self,
        *,
        request: ToolCallRequest,
        status: ToolCallStatus,
        input_redacted_json: dict[str, Any],
        output_redacted_json: dict[str, Any] | None,
        error_code: str | None,
    ) -> ToolAuditRecord:
        """Write.

        Args:
            request: ToolCallRequest: .
            status: ToolCallStatus: .
            input_redacted_json: dict[str, Any]: .
            output_redacted_json: dict[str, Any] | None: .
            error_code: str | None: .

        Returns:
            ToolAuditRecord: .
        """
        now = datetime.now(UTC)
        audit_ref = f"tool_audit_{request.tool_call_id}"
        record = ToolAuditRecord(
            audit_ref=audit_ref,
            tool_call_id=request.tool_call_id,
            run_id=request.run_id,
            task_id=request.task_id,
            caller_agent=request.caller_agent,
            tool_name=request.tool_name,
            tool_version=request.tool_version,
            input_hash=stable_json_hash(request.input_json),
            input_redacted_json=input_redacted_json,
            output_hash=(
                None if output_redacted_json is None else stable_json_hash(output_redacted_json)
            ),
            output_redacted_json=output_redacted_json,
            status=status,
            error_code=error_code,
            started_at=now,
            finished_at=now,
        )
        self.records[audit_ref] = record
        return record
