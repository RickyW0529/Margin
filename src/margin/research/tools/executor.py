"""Schema-validating scoped tool executor and audit contracts."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from time import perf_counter
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from margin.news.models import utc_now
from margin.research.tools.definitions import ToolDefinition
from margin.research.tools.policy import ToolPolicyDecision


class ScopedToolResult(BaseModel):
    """Sanitized result returned to graph node code."""

    call_id: str
    tool_name: str
    success: bool
    data: Any = None
    error_code: str | None = None

    model_config = {"frozen": True}


class ToolCallAuditRecord(BaseModel):
    """Secret-safe audit record for one scoped tool attempt."""

    call_id: str
    graph_run_id: str
    node_name: str
    tool_name: str
    tool_version: str
    capability: str
    policy_version: str
    allowed: bool
    success: bool
    request_hash: str
    response_hash: str | None = None
    request_metadata: dict[str, Any]
    response_metadata: dict[str, Any]
    result_bytes: int = 0
    latency_ms: float = 0.0
    error_code: str | None = None
    created_at: datetime

    model_config = {"frozen": True}


class ToolCallAuditRepository(Protocol):
    """Persistence boundary used by the scoped executor."""

    def add(self, record: ToolCallAuditRecord) -> None:
        """Persist one immutable audit record."""


class MemoryToolCallAuditRepository:
    """Append-only process-local audit repository."""

    def __init__(self) -> None:
        """Initialize the instance."""
        self._records: dict[str, ToolCallAuditRecord] = {}

    def add(self, record: ToolCallAuditRecord) -> None:
        """add."""
        current = self._records.get(record.call_id)
        if current is not None and current != record:
            raise ValueError(f"tool call audit '{record.call_id}' is immutable")
        self._records[record.call_id] = record

    @property
    def records(self) -> tuple[ToolCallAuditRecord, ...]:
        """Return records in insertion order."""
        return tuple(self._records.values())


class ToolExecutor:
    """Execute a policy-approved definition with schema and byte limits."""

    def __init__(
        self,
        audit_repository: ToolCallAuditRepository | None = None,
    ) -> None:
        """Initialize the instance."""
        self._audit = audit_repository or MemoryToolCallAuditRepository()

    def denied(
        self,
        *,
        graph_run_id: str,
        node_name: str,
        definition: ToolDefinition,
        args: dict[str, Any],
        decision: ToolPolicyDecision,
    ) -> ScopedToolResult:
        """Audit and return a deterministic policy denial."""
        call_id = _call_id()
        self._audit.add(
            _audit_record(
                call_id=call_id,
                graph_run_id=graph_run_id,
                node_name=node_name,
                definition=definition,
                args=args,
                decision=decision,
                success=False,
                error_code=decision.reason_code,
            )
        )
        return ScopedToolResult(
            call_id=call_id,
            tool_name=definition.name,
            success=False,
            error_code=decision.reason_code,
        )

    def unknown(
        self,
        *,
        graph_run_id: str,
        node_name: str,
        tool_name: str,
        args: dict[str, Any],
        policy_version: str,
    ) -> ScopedToolResult:
        """Audit and reject a call to an unregistered tool."""
        call_id = _call_id()
        self._audit.add(
            ToolCallAuditRecord(
                call_id=call_id,
                graph_run_id=graph_run_id,
                node_name=node_name,
                tool_name=tool_name,
                tool_version="unregistered",
                capability="unknown",
                policy_version=policy_version,
                allowed=False,
                success=False,
                request_hash=_hash_payload(args),
                request_metadata={"keys": sorted(args)},
                response_metadata={},
                error_code="tool_not_registered",
                created_at=utc_now(),
            )
        )
        return ScopedToolResult(
            call_id=call_id,
            tool_name=tool_name,
            success=False,
            error_code="tool_not_registered",
        )

    def execute(
        self,
        *,
        graph_run_id: str,
        node_name: str,
        definition: ToolDefinition,
        args: dict[str, Any],
        decision: ToolPolicyDecision,
        max_result_bytes: int,
    ) -> ScopedToolResult:
        """Validate args, invoke the handler, enforce bytes, and append audit."""
        call_id = _call_id()
        started = perf_counter()
        try:
            validated_args = definition.validate_args(args)
        except ValidationError:
            return self._failure(
                call_id=call_id,
                graph_run_id=graph_run_id,
                node_name=node_name,
                definition=definition,
                args=args,
                decision=decision,
                error_code="schema_validation_failed",
                latency_ms=(perf_counter() - started) * 1_000,
            )

        try:
            data = definition.handler(validated_args)
        except Exception:  # noqa: BLE001 - external error text is not exposed
            return self._failure(
                call_id=call_id,
                graph_run_id=graph_run_id,
                node_name=node_name,
                definition=definition,
                args=args,
                decision=decision,
                error_code="tool_execution_failed",
                latency_ms=(perf_counter() - started) * 1_000,
            )

        encoded = json.dumps(
            data,
            sort_keys=True,
            default=str,
            separators=(",", ":"),
        ).encode("utf-8")
        latency_ms = (perf_counter() - started) * 1_000
        if len(encoded) > max_result_bytes:
            return self._failure(
                call_id=call_id,
                graph_run_id=graph_run_id,
                node_name=node_name,
                definition=definition,
                args=args,
                decision=decision,
                error_code="result_too_large",
                latency_ms=latency_ms,
                result_bytes=len(encoded),
            )

        response_hash = _hash_bytes(encoded)
        self._audit.add(
            _audit_record(
                call_id=call_id,
                graph_run_id=graph_run_id,
                node_name=node_name,
                definition=definition,
                args=args,
                decision=decision,
                success=True,
                response_hash=response_hash,
                response_metadata={"type": type(data).__name__},
                result_bytes=len(encoded),
                latency_ms=latency_ms,
            )
        )
        return ScopedToolResult(
            call_id=call_id,
            tool_name=definition.name,
            success=True,
            data=data,
        )

    def _failure(
        self,
        *,
        call_id: str,
        graph_run_id: str,
        node_name: str,
        definition: ToolDefinition,
        args: dict[str, Any],
        decision: ToolPolicyDecision,
        error_code: str,
        latency_ms: float,
        result_bytes: int = 0,
    ) -> ScopedToolResult:
        """failure."""
        self._audit.add(
            _audit_record(
                call_id=call_id,
                graph_run_id=graph_run_id,
                node_name=node_name,
                definition=definition,
                args=args,
                decision=decision,
                success=False,
                error_code=error_code,
                result_bytes=result_bytes,
                latency_ms=latency_ms,
            )
        )
        return ScopedToolResult(
            call_id=call_id,
            tool_name=definition.name,
            success=False,
            error_code=error_code,
        )


def _audit_record(
    *,
    call_id: str,
    graph_run_id: str,
    node_name: str,
    definition: ToolDefinition,
    args: dict[str, Any],
    decision: ToolPolicyDecision,
    success: bool,
    response_hash: str | None = None,
    request_metadata: dict[str, Any] | None = None,
    response_metadata: dict[str, Any] | None = None,
    result_bytes: int = 0,
    latency_ms: float = 0.0,
    error_code: str | None = None,
) -> ToolCallAuditRecord:
    """audit record."""
    return ToolCallAuditRecord(
        call_id=call_id,
        graph_run_id=graph_run_id,
        node_name=node_name,
        tool_name=definition.name,
        tool_version=definition.version,
        capability=definition.capability.value,
        policy_version=decision.policy_version,
        allowed=decision.allowed,
        success=success,
        request_hash=_hash_payload(args),
        response_hash=response_hash,
        request_metadata=request_metadata or {"keys": sorted(args)},
        response_metadata=response_metadata or {},
        result_bytes=result_bytes,
        latency_ms=latency_ms,
        error_code=error_code,
        created_at=utc_now(),
    )


def _hash_payload(payload: Any) -> str:
    """hash payload."""
    encoded = json.dumps(
        payload,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    ).encode("utf-8")
    return _hash_bytes(encoded)


def _hash_bytes(payload: bytes) -> str:
    """hash bytes."""
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _call_id() -> str:
    """call id."""
    return "tc_" + uuid.uuid4().hex[:24]
