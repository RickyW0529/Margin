"""Audit repository for immutable business records.

Provides a Protocol defining the audit persistence contract together with
in-memory and SQLAlchemy-backed implementations. Repositories enforce
immutability by rejecting duplicate ``record_id`` values.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from margin.core.db_audit import AuditLogRecordRow
from margin.core.models import AuditLogRecord


class AuditRepository(Protocol):
    """Persistence contract for immutable audit records."""

    def record(self, record: AuditLogRecord) -> None:
        """Append an audit record."""
        ...

    def list_records(
        self,
        record_type: str | None = None,
        object_id: str | None = None,
        trace_id: str | None = None,
        limit: int = 100,
    ) -> list[AuditLogRecord]:
        """Return audit records ordered by recorded_at desc."""
        ...


class MemoryAuditRepository:
    """In-memory audit repository for tests."""

    def __init__(self) -> None:
        self._records: dict[str, AuditLogRecord] = {}

    def record(self, record: AuditLogRecord) -> None:
        # Reject duplicates to preserve the append-only / immutable contract in memory.
        if record.record_id in self._records:
            raise ValueError(f"audit record '{record.record_id}' already exists")
        self._records[record.record_id] = record

    def list_records(
        self,
        record_type: str | None = None,
        object_id: str | None = None,
        trace_id: str | None = None,
        limit: int = 100,
    ) -> list[AuditLogRecord]:
        records = list(self._records.values())
        if record_type is not None:
            records = [r for r in records if r.record_type == record_type]
        if object_id is not None:
            records = [r for r in records if r.object_id == object_id]
        if trace_id is not None:
            records = [r for r in records if r.trace_id == trace_id]
        # Most recent first matches the SQLAlchemy ordering used in production.
        records = sorted(records, key=lambda r: r.recorded_at, reverse=True)
        return records[:limit]


class SQLAlchemyAuditRepository:
    """PostgreSQL audit repository."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def record(self, record: AuditLogRecord) -> None:
        # ``begin()`` commits on success and rolls back on exception automatically.
        with self._session_factory.begin() as session:
            session.add(_record_to_row(record))

    def list_records(
        self,
        record_type: str | None = None,
        object_id: str | None = None,
        trace_id: str | None = None,
        limit: int = 100,
    ) -> list[AuditLogRecord]:
        statement = select(AuditLogRecordRow).order_by(AuditLogRecordRow.recorded_at.desc())
        if record_type is not None:
            statement = statement.where(AuditLogRecordRow.record_type == record_type)
        if object_id is not None:
            statement = statement.where(AuditLogRecordRow.object_id == object_id)
        if trace_id is not None:
            statement = statement.where(AuditLogRecordRow.trace_id == trace_id)
        statement = statement.limit(limit)
        with self._session_factory() as session:
            return [_record_from_row(row) for row in session.scalars(statement).all()]


def _record_to_row(record: AuditLogRecord) -> AuditLogRecordRow:
    """Map a domain audit record to its SQLAlchemy row representation."""
    return AuditLogRecordRow(
        record_id=record.record_id,
        record_type=record.record_type,
        object_id=record.object_id,
        trace_id=record.trace_id,
        input_hash=record.input_hash,
        output_hash=record.output_hash,
        payload_json=record.payload_json,
        recorded_at=record.recorded_at,
        service_version=record.service_version,
    )


def _record_from_row(row: AuditLogRecordRow) -> AuditLogRecord:
    """Map a SQLAlchemy row back to the domain audit record."""
    return AuditLogRecord(
        record_id=row.record_id,
        record_type=row.record_type,
        object_id=row.object_id,
        trace_id=row.trace_id,
        input_hash=row.input_hash,
        output_hash=row.output_hash,
        # Copy JSONB payload into a plain dict so callers cannot mutate the ORM state.
        payload_json=dict(row.payload_json) if row.payload_json is not None else None,
        recorded_at=row.recorded_at,
        service_version=row.service_version,
    )
