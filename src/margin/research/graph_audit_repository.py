"""DB-backed audit repositories for v0.2 graph LLM and tool calls."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.orm import Session

from margin.research.db_models import LLMCallRecordRow, ToolCallRecordRow
from margin.research.execution.llm_service import LLMCallAuditRecord
from margin.research.tools.executor import ToolCallAuditRecord
from margin.sql.research_queries import llm_call_by_billing_key


class SQLAlchemyLLMCallAuditRepository:
    """Persist hash-only LLM call audit records idempotently."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        """Initialize the repository.

        Args:
            session_factory: Callable that returns a new SQLAlchemy ``Session``.
        """
        self._session_factory = session_factory

    def add(self, record: LLMCallAuditRecord) -> None:
        """Persist one immutable LLM call audit record.

        Args:
            record: Hash-only audit record to persist.

        Raises:
            ValueError: If a conflicting record with the same billing key exists.
        """
        with self._session_factory.begin() as session:
            existing = session.scalars(
                llm_call_by_billing_key(record.billing_key)
            ).first()
            if existing is not None:
                if _llm_record_from_row(existing) != record:
                    raise ValueError("conflicting LLM call audit record")
                return
            session.add(_llm_record_to_row(record))


class SQLAlchemyToolCallAuditRepository:
    """Persist scoped tool call audit records idempotently."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        """Initialize the repository.

        Args:
            session_factory: Callable that returns a new SQLAlchemy ``Session``.
        """
        self._session_factory = session_factory

    def add(self, record: ToolCallAuditRecord) -> None:
        """Persist one immutable scoped-tool audit record.

        Args:
            record: Secret-safe audit record to persist.

        Raises:
            ValueError: If a conflicting record with the same call ID exists.
        """
        with self._session_factory.begin() as session:
            existing = session.get(ToolCallRecordRow, record.call_id)
            if existing is not None:
                if _tool_record_from_row(existing) != record:
                    raise ValueError("conflicting tool call audit record")
                return
            session.add(_tool_record_to_row(record))


def _llm_record_to_row(record: LLMCallAuditRecord) -> LLMCallRecordRow:
    """Convert a hash-only LLM audit record to a DB row."""
    model_name = record.model_name or record.model or "unknown"
    provider_name = record.provider_name or "unknown"
    model_version = record.model_version or record.model or "unknown"
    return LLMCallRecordRow(
        llm_call_id=record.call_id,
        billing_key=record.billing_key,
        graph_run_id=record.graph_run_id,
        node_name=record.node_name,
        task_type=record.task_type,
        provider_name=provider_name,
        model_name=model_name,
        model_version=model_version,
        prompt_version=record.prompt_version,
        prompt_hash=record.prompt_hash,
        schema_hash=record.schema_hash,
        request_hash=record.request_hash,
        response_hash=record.response_hash,
        input_tokens=record.input_tokens,
        output_tokens=record.output_tokens,
        total_tokens=record.total_tokens,
        cost_usd=record.cost_usd,
        latency_ms=record.latency_ms,
        success=record.success,
        error_code=record.error_code,
        request_metadata=dict(record.request_metadata),
        response_metadata=dict(record.response_metadata),
        created_at=record.created_at,
    )


def _llm_record_from_row(row: LLMCallRecordRow) -> LLMCallAuditRecord:
    """Convert a DB row to a hash-only LLM audit record."""
    return LLMCallAuditRecord(
        call_id=row.llm_call_id,
        billing_key=row.billing_key,
        graph_run_id=row.graph_run_id,
        node_name=row.node_name,
        task_type=row.task_type,
        model=str(row.response_metadata.get("model", "")),
        provider_name=row.provider_name,
        model_name=row.model_name,
        model_version=row.model_version,
        prompt_version=row.prompt_version,
        prompt_hash=row.prompt_hash,
        schema_hash=row.schema_hash,
        request_hash=row.request_hash,
        response_hash=row.response_hash,
        latency_ms=row.latency_ms or 0.0,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        total_tokens=row.total_tokens,
        cost_usd=row.cost_usd,
        success=row.success,
        error_code=row.error_code,
        request_metadata=dict(row.request_metadata),
        response_metadata=dict(row.response_metadata),
        created_at=row.created_at,
    )


def _tool_record_to_row(record: ToolCallAuditRecord) -> ToolCallRecordRow:
    """Convert a scoped-tool audit record to a DB row."""
    return ToolCallRecordRow(
        tool_call_id=record.call_id,
        graph_run_id=record.graph_run_id,
        node_name=record.node_name,
        capability=record.capability,
        tool_name=record.tool_name,
        tool_version=record.tool_version,
        policy_version=record.policy_version,
        allowed=record.allowed,
        success=record.success,
        request_hash=record.request_hash,
        response_hash=record.response_hash,
        request_metadata=dict(record.request_metadata),
        response_metadata=dict(record.response_metadata),
        result_bytes=record.result_bytes,
        latency_ms=record.latency_ms,
        error_code=record.error_code,
        created_at=record.created_at,
    )


def _tool_record_from_row(row: ToolCallRecordRow) -> ToolCallAuditRecord:
    """Convert a scoped-tool audit row to its immutable model."""
    return ToolCallAuditRecord(
        call_id=row.tool_call_id,
        graph_run_id=row.graph_run_id,
        node_name=row.node_name,
        tool_name=row.tool_name,
        tool_version=row.tool_version,
        capability=row.capability,
        policy_version=row.policy_version,
        allowed=row.allowed,
        success=row.success,
        request_hash=row.request_hash,
        response_hash=row.response_hash,
        request_metadata=dict(row.request_metadata),
        response_metadata=dict(row.response_metadata),
        result_bytes=row.result_bytes,
        latency_ms=row.latency_ms or 0.0,
        error_code=row.error_code,
        created_at=row.created_at,
    )
