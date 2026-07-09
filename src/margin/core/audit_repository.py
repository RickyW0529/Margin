"""Audit repository for immutable business records.

Provides a Protocol defining the audit persistence contract together with
in-memory and SQLAlchemy-backed implementations. Repositories enforce
immutability by rejecting duplicate ``record_id`` values.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from sqlalchemy.orm import Session

from margin.core.audit import SecretRedactingProcessor
from margin.core.db_audit import AuditLogRecordRow
from margin.core.models import AuditLogRecord
from margin.sql.core_queries import audit_records

AuditRedactor = Callable[[object, str, dict[str, Any]], dict[str, Any]]


class AuditRepository(Protocol):
    """Persistence contract for immutable audit records.."""

    def record(self, record: AuditLogRecord) -> None:
        """Append an audit record.

        Args:
            record: AuditLogRecord: .

        Returns:
            None: .
        """
        ...

    def list_records(
        self,
        record_type: str | None = None,
        object_id: str | None = None,
        trace_id: str | None = None,
        limit: int = 100,
    ) -> list[AuditLogRecord]:
        """Return audit records ordered by recorded_at desc.

        Args:
            record_type: str | None: .
            object_id: str | None: .
            trace_id: str | None: .
            limit: int: .

        Returns:
            list[AuditLogRecord]: .
        """
        ...


class MemoryAuditRepository:
    """In-memory audit repository for tests.."""

    def __init__(self, redactor: AuditRedactor | None = None) -> None:
        """Initialize an empty in-memory repository.

        Args:
            redactor: AuditRedactor | None: .

        Returns:
            None: .
        """
        self._records: dict[str, AuditLogRecord] = {}
        self._redactor = redactor or SecretRedactingProcessor()

    def record(self, record: AuditLogRecord) -> None:
        """Append an audit record, rejecting duplicate ids.

        Args:
            record: AuditLogRecord: .

        Returns:
            None: .
        """
        # Reject duplicates to preserve the append-only / immutable contract in memory.
        sanitized = _sanitize_record(record, self._redactor)
        if sanitized.record_id in self._records:
            raise ValueError(f"audit record '{record.record_id}' already exists")
        self._records[sanitized.record_id] = sanitized

    def list_records(
        self,
        record_type: str | None = None,
        object_id: str | None = None,
        trace_id: str | None = None,
        limit: int = 100,
    ) -> list[AuditLogRecord]:
        """Return in-memory audit records ordered by recorded_at desc.

        Args:
            record_type: str | None: .
            object_id: str | None: .
            trace_id: str | None: .
            limit: int: .

        Returns:
            list[AuditLogRecord]: .
        """
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
    """PostgreSQL audit repository backed by SQLAlchemy.."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        redactor: AuditRedactor | None = None,
    ) -> None:
        """Initialize the repository.

        Args:
            session_factory: Callable[[], Session]: .
            redactor: AuditRedactor | None: .

        Returns:
            None: .
        """
        self._session_factory = session_factory
        self._redactor = redactor or SecretRedactingProcessor()

    def record(self, record: AuditLogRecord) -> None:
        """Persist an audit record to PostgreSQL.

        Args:
            record: AuditLogRecord: .

        Returns:
            None: .
        """
        # ``begin()`` commits on success and rolls back on exception automatically.
        sanitized = _sanitize_record(record, self._redactor)
        with self._session_factory.begin() as session:
            session.add(_record_to_row(sanitized))

    def list_records(
        self,
        record_type: str | None = None,
        object_id: str | None = None,
        trace_id: str | None = None,
        limit: int = 100,
    ) -> list[AuditLogRecord]:
        """Return persisted audit records ordered by recorded_at desc.

        Args:
            record_type: str | None: .
            object_id: str | None: .
            trace_id: str | None: .
            limit: int: .

        Returns:
            list[AuditLogRecord]: .
        """
        statement = audit_records(
            record_type=record_type,
            object_id=object_id,
            trace_id=trace_id,
            limit=limit,
        )
        with self._session_factory() as session:
            return [_record_from_row(row) for row in session.scalars(statement).all()]


def _record_to_row(record: AuditLogRecord) -> AuditLogRecordRow:
    """Map a domain audit record to its SQLAlchemy row representation.

    Args:
        record: AuditLogRecord: .

    Returns:
        AuditLogRecordRow: .
    """
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


def _sanitize_record(record: AuditLogRecord, redactor: AuditRedactor) -> AuditLogRecord:
    """Return a copy whose structured payload has been recursively redacted.

    Args:
        record: AuditLogRecord: .
        redactor: AuditRedactor: .

    Returns:
        AuditLogRecord: .
    """
    if record.payload_json is None:
        return record
    return record.model_copy(
        update={"payload_json": redactor(None, "audit", dict(record.payload_json))}
    )


def _record_from_row(row: AuditLogRecordRow) -> AuditLogRecord:
    """Map a SQLAlchemy row back to the domain audit record.

    Args:
        row: AuditLogRecordRow: .

    Returns:
        AuditLogRecord: .
    """
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
