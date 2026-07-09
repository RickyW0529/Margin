"""ToolGateway audit records."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from margin.agents.tools.db_models import ToolCallRow, ToolResultRow
from margin.agents.tools.specs import ToolCallRequest, ToolCallStatus
from margin.core.hashing import stable_json_hash


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

    def get_record(self, audit_ref: str) -> ToolAuditRecord | None:
        """Return one audit record by reference.

        Args:
            audit_ref: Stable audit reference.

        Returns:
            Matching record, if present.
        """
        return self.records.get(audit_ref)

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


class SQLAlchemyToolAuditStore:
    """SQLAlchemy-backed ToolGateway audit store."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        """Initialize with a SQLAlchemy session factory."""
        self._session_factory = session_factory

    def get_record(self, audit_ref: str) -> ToolAuditRecord | None:
        """Return one audit record by reference.

        Args:
            audit_ref: Stable audit reference.

        Returns:
            Matching record, if present.
        """
        tool_call_id = _tool_call_id_from_audit_ref(audit_ref)
        with self._session_factory() as session:
            call_row = session.get(ToolCallRow, tool_call_id)
            if call_row is None:
                return None
            result_row = session.get(ToolResultRow, tool_call_id)
            return _record_from_rows(call_row, result_row)

    def write(
        self,
        *,
        request: ToolCallRequest,
        status: ToolCallStatus,
        input_redacted_json: dict[str, Any],
        output_redacted_json: dict[str, Any] | None,
        error_code: str | None,
    ) -> ToolAuditRecord:
        """Write or replay one idempotent audit record.

        Args:
            request: Tool call request.
            status: Tool call status.
            input_redacted_json: Redacted input payload.
            output_redacted_json: Redacted output payload, if any.
            error_code: Optional stable error code.

        Returns:
            Persisted audit record.
        """
        now = datetime.now(UTC)
        output_bytes = _json_size(output_redacted_json)
        output_hash = (
            None if output_redacted_json is None else stable_json_hash(output_redacted_json)
        )
        call_payload = ToolCallRow(
            tool_call_id=request.tool_call_id,
            run_id=request.run_id,
            task_id=request.task_id,
            caller_agent=request.caller_agent,
            tool_name=request.tool_name,
            tool_version=request.tool_version,
            input_hash=stable_json_hash(request.input_json),
            input_redacted_json=input_redacted_json,
            capability_token_id=request.capability_token.token_id,
            idempotency_key=request.idempotency_key,
            status=status.value,
            started_at=now,
            finished_at=now,
            error_code=error_code,
            retryable=False,
        )
        result_payload = ToolResultRow(
            tool_call_id=request.tool_call_id,
            output_hash=output_hash,
            output_redacted_json=output_redacted_json,
            output_artifact_refs=[],
            output_bytes=output_bytes,
            created_at=now,
        )
        with self._session_factory() as session, session.begin():
            existing_call = session.get(ToolCallRow, request.tool_call_id)
            if existing_call is None:
                session.add(call_payload)
                session.add(result_payload)
            else:
                existing_result = session.get(ToolResultRow, request.tool_call_id)
                return _record_from_rows(existing_call, existing_result)
        return self.get_record(f"tool_audit_{request.tool_call_id}")  # type: ignore[return-value]


def _tool_call_id_from_audit_ref(audit_ref: str) -> str:
    """Extract tool call id from the stable audit ref."""
    return audit_ref.removeprefix("tool_audit_")


def _record_from_rows(
    call_row: ToolCallRow,
    result_row: ToolResultRow | None,
) -> ToolAuditRecord:
    """Convert SQLAlchemy rows to an audit record."""
    return ToolAuditRecord(
        audit_ref=f"tool_audit_{call_row.tool_call_id}",
        tool_call_id=call_row.tool_call_id,
        run_id=call_row.run_id,
        task_id=call_row.task_id,
        caller_agent=call_row.caller_agent,
        tool_name=call_row.tool_name,
        tool_version=call_row.tool_version,
        input_hash=call_row.input_hash,
        input_redacted_json=call_row.input_redacted_json,
        output_hash=None if result_row is None else result_row.output_hash,
        output_redacted_json=None if result_row is None else result_row.output_redacted_json,
        status=ToolCallStatus(call_row.status),
        error_code=call_row.error_code,
        started_at=call_row.started_at,
        finished_at=call_row.finished_at or call_row.started_at,
    )


def _json_size(value: dict[str, Any] | None) -> int:
    """Return UTF-8 JSON size for persisted redacted output."""
    if value is None:
        return 0
    import json

    return len(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8"))
