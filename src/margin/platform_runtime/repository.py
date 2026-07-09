"""Repositories for platform and ops runtime records."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from margin.platform_runtime.db_models import (
    DataFreshnessStateRow,
    DeadLetterQueueRow,
    IdempotencyKeyRow,
    OutboxEventRow,
    SystemHealthSnapshotRow,
)

_REDACTED = "[REDACTED]"
_SENSITIVE_KEY_FRAGMENTS = (
    "api_key",
    "apikey",
    "authorization",
    "password",
    "provider_token",
    "raw_payload",
    "raw_text",
    "secret",
    "token",
)


class IdempotencyKeyRecord(BaseModel):
    """Replay guard for one idempotent request."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    idempotency_key: str
    scope: str
    request_hash: str
    response_hash: str | None = None
    response_ref: str | None = None
    status: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime


class OutboxEvent(BaseModel):
    """Platform outbox event metadata."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str
    aggregate_type: str
    aggregate_id: str
    event_type: str
    payload_json: dict[str, Any]
    status: str = "pending"
    attempts: int = 0
    next_attempt_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    processed_at: datetime | None = None


class DeadLetterRecord(BaseModel):
    """Redacted dead-letter payload for a failed runtime event."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dlq_id: int
    source_table: str
    source_id: str
    error_code: str
    error_message: str | None
    payload_redacted_json: dict[str, Any] | None
    created_at: datetime


class SystemHealthSnapshot(BaseModel):
    """Component health snapshot."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    health_snapshot_id: str
    component_name: str
    status: str
    metrics_json: dict[str, Any] = Field(default_factory=dict)
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DataFreshnessState(BaseModel):
    """Dataset freshness state used by ops and dashboard views."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    freshness_state_id: str
    dataset_name: str
    provider_name: str | None = None
    latest_available_date: date | None = None
    latest_fetched_at: datetime | None = None
    stale_after_seconds: int | None = None
    freshness_status: str
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class MemoryIdempotencyStore:
    """Process-local idempotency store for tests and single-process personal mode."""

    def __init__(self) -> None:
        """Initialize an empty in-memory store."""
        self._records: dict[str, IdempotencyKeyRecord] = {}

    def record_idempotency_key(self, record: IdempotencyKeyRecord) -> None:
        """Persist one idempotency record idempotently."""
        current = self._records.get(record.idempotency_key)
        if current is None:
            self._records[record.idempotency_key] = record
            return
        if current != record:
            raise ValueError(f"idempotency key '{record.idempotency_key}' is immutable")

    def get_idempotency_key(self, idempotency_key: str) -> IdempotencyKeyRecord | None:
        """Return one idempotency record by key."""
        return self._records.get(idempotency_key)

    def begin_idempotency_key(
        self,
        record: IdempotencyKeyRecord,
    ) -> IdempotencyKeyRecord | None:
        """Reserve an idempotency key before side effects run.

        Returns the existing record when another request has already claimed
        the key; otherwise stores ``record`` and returns ``None``.
        """
        current = self._records.get(record.idempotency_key)
        if current is not None:
            return current
        self._records[record.idempotency_key] = record
        return None

    def complete_idempotency_key(self, record: IdempotencyKeyRecord) -> IdempotencyKeyRecord:
        """Mark a reserved idempotency key completed."""
        current = self._records.get(record.idempotency_key)
        if current is None:
            self._records[record.idempotency_key] = record
            return record
        if current.request_hash != record.request_hash or current.scope != record.scope:
            raise ValueError(f"idempotency key '{record.idempotency_key}' is immutable")
        if current.status == "completed":
            return current
        self._records[record.idempotency_key] = record
        return record


class SQLAlchemyPlatformRuntimeRepository:
    """SQLAlchemy-backed repository for platform and ops runtime records."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        """Initialize the repository with a session factory."""
        self._session_factory = session_factory

    def record_idempotency_key(self, record: IdempotencyKeyRecord) -> None:
        """Persist one idempotency record idempotently."""
        with self._session_factory() as session, session.begin():
            current = session.get(IdempotencyKeyRow, record.idempotency_key)
            if current is None:
                session.add(_idempotency_row(record))
                return
            if _idempotency_payload(current) != record:
                raise ValueError(f"idempotency key '{record.idempotency_key}' is immutable")

    def get_idempotency_key(self, idempotency_key: str) -> IdempotencyKeyRecord | None:
        """Return one idempotency record by key."""
        with self._session_factory() as session:
            row = session.get(IdempotencyKeyRow, idempotency_key)
            return _idempotency_payload(row) if row is not None else None

    def begin_idempotency_key(
        self,
        record: IdempotencyKeyRecord,
    ) -> IdempotencyKeyRecord | None:
        """Reserve an idempotency key before side effects run."""
        from sqlalchemy.exc import IntegrityError

        try:
            with self._session_factory() as session, session.begin():
                current = session.get(IdempotencyKeyRow, record.idempotency_key)
                if current is not None:
                    return _idempotency_payload(current)
                session.add(_idempotency_row(record))
                return None
        except IntegrityError:
            existing = self.get_idempotency_key(record.idempotency_key)
            if existing is not None:
                return existing
            raise

    def complete_idempotency_key(self, record: IdempotencyKeyRecord) -> IdempotencyKeyRecord:
        """Mark a reserved idempotency key completed."""
        with self._session_factory() as session, session.begin():
            row = session.get(IdempotencyKeyRow, record.idempotency_key)
            if row is None:
                session.add(_idempotency_row(record))
                return record
            current = _idempotency_payload(row)
            if current.request_hash != record.request_hash or current.scope != record.scope:
                raise ValueError(f"idempotency key '{record.idempotency_key}' is immutable")
            if current.status == "completed":
                return current
            row.response_hash = record.response_hash
            row.response_ref = record.response_ref
            row.status = record.status
            row.expires_at = record.expires_at
            return record

    def enqueue_outbox_event(self, event: OutboxEvent) -> None:
        """Append one platform outbox event."""
        with self._session_factory() as session, session.begin():
            current = session.get(OutboxEventRow, event.event_id)
            if current is None:
                session.add(_outbox_row(event))
                return
            if _outbox_payload(current) != event:
                raise ValueError(f"outbox event '{event.event_id}' is immutable")

    def claim_due_outbox_events(self, *, now: datetime, limit: int) -> list[OutboxEvent]:
        """Return due outbox events without mutating delivery state."""
        with self._session_factory() as session:
            rows = session.scalars(
                select(OutboxEventRow)
                .where(
                    and_(
                        OutboxEventRow.status == "pending",
                        or_(
                            OutboxEventRow.next_attempt_at.is_(None),
                            OutboxEventRow.next_attempt_at <= now,
                        ),
                    )
                )
                .order_by(OutboxEventRow.created_at, OutboxEventRow.event_id)
                .limit(limit)
            ).all()
            return [_outbox_payload(row) for row in rows]

    def mark_outbox_retry(self, event_id: str, *, next_attempt_at: datetime) -> None:
        """Record one retry attempt and schedule the next delivery attempt."""
        with self._session_factory() as session, session.begin():
            row = session.get(OutboxEventRow, event_id)
            if row is None:
                raise KeyError(f"outbox event not found: {event_id}")
            row.status = "pending"
            row.attempts += 1
            row.next_attempt_at = next_attempt_at

    def get_outbox_event(self, event_id: str) -> OutboxEvent | None:
        """Return one platform outbox event by id."""
        with self._session_factory() as session:
            row = session.get(OutboxEventRow, event_id)
            return _outbox_payload(row) if row is not None else None

    def record_dead_letter(
        self,
        *,
        source_table: str,
        source_id: str,
        error_code: str,
        error_message: str | None,
        payload_json: dict[str, Any] | None,
    ) -> DeadLetterRecord:
        """Persist a redacted dead-letter payload."""
        with self._session_factory() as session, session.begin():
            row = DeadLetterQueueRow(
                source_table=source_table,
                source_id=source_id,
                error_code=error_code,
                error_message=error_message,
                payload_redacted_json=_redact_payload(payload_json) if payload_json else None,
                created_at=datetime.now(UTC),
            )
            session.add(row)
            session.flush()
            return _dead_letter_payload(row)

    def get_dead_letter_record(self, dlq_id: int) -> DeadLetterRecord | None:
        """Return a redacted dead-letter record by id."""
        with self._session_factory() as session:
            row = session.get(DeadLetterQueueRow, dlq_id)
            return _dead_letter_payload(row) if row is not None else None

    def record_system_health_snapshot(self, snapshot: SystemHealthSnapshot) -> None:
        """Persist one immutable system health snapshot."""
        with self._session_factory() as session, session.begin():
            current = session.get(SystemHealthSnapshotRow, snapshot.health_snapshot_id)
            if current is None:
                session.add(_health_row(snapshot))
                return
            if _health_payload(current) != snapshot:
                raise ValueError(
                    f"system health snapshot '{snapshot.health_snapshot_id}' is immutable"
                )

    def get_system_health_snapshot(
        self,
        health_snapshot_id: str,
    ) -> SystemHealthSnapshot | None:
        """Return a system health snapshot by id."""
        with self._session_factory() as session:
            row = session.get(SystemHealthSnapshotRow, health_snapshot_id)
            return _health_payload(row) if row is not None else None

    def record_data_freshness_state(self, state: DataFreshnessState) -> None:
        """Persist or replace the latest state for one freshness id."""
        with self._session_factory() as session, session.begin():
            row = session.get(DataFreshnessStateRow, state.freshness_state_id)
            if row is None:
                session.add(_freshness_row(state))
                return
            replacement = _freshness_row(state)
            row.dataset_name = replacement.dataset_name
            row.provider_name = replacement.provider_name
            row.latest_available_date = replacement.latest_available_date
            row.latest_fetched_at = replacement.latest_fetched_at
            row.stale_after_seconds = replacement.stale_after_seconds
            row.freshness_status = replacement.freshness_status
            row.checked_at = replacement.checked_at

    def get_data_freshness_state(self, freshness_state_id: str) -> DataFreshnessState | None:
        """Return one data freshness state by id."""
        with self._session_factory() as session:
            row = session.get(DataFreshnessStateRow, freshness_state_id)
            return _freshness_payload(row) if row is not None else None


def _idempotency_row(record: IdempotencyKeyRecord) -> IdempotencyKeyRow:
    """Convert an idempotency record to an ORM row."""
    return IdempotencyKeyRow(**record.model_dump(mode="python"))


def _idempotency_payload(row: IdempotencyKeyRow) -> IdempotencyKeyRecord:
    """Convert an idempotency row to a model."""
    return IdempotencyKeyRecord(
        idempotency_key=row.idempotency_key,
        scope=row.scope,
        request_hash=row.request_hash,
        response_hash=row.response_hash,
        response_ref=row.response_ref,
        status=row.status,
        created_at=row.created_at,
        expires_at=row.expires_at,
    )


def _outbox_row(event: OutboxEvent) -> OutboxEventRow:
    """Convert an outbox event to an ORM row."""
    return OutboxEventRow(**event.model_dump(mode="python"))


def _outbox_payload(row: OutboxEventRow) -> OutboxEvent:
    """Convert an outbox row to a model."""
    return OutboxEvent(
        event_id=row.event_id,
        aggregate_type=row.aggregate_type,
        aggregate_id=row.aggregate_id,
        event_type=row.event_type,
        payload_json=row.payload_json,
        status=row.status,
        attempts=row.attempts,
        next_attempt_at=row.next_attempt_at,
        created_at=row.created_at,
        processed_at=row.processed_at,
    )


def _dead_letter_payload(row: DeadLetterQueueRow) -> DeadLetterRecord:
    """Convert a dead-letter row to a model."""
    return DeadLetterRecord(
        dlq_id=row.dlq_id,
        source_table=row.source_table,
        source_id=row.source_id,
        error_code=row.error_code,
        error_message=row.error_message,
        payload_redacted_json=row.payload_redacted_json,
        created_at=row.created_at,
    )


def _health_row(snapshot: SystemHealthSnapshot) -> SystemHealthSnapshotRow:
    """Convert a system health snapshot to an ORM row."""
    return SystemHealthSnapshotRow(**snapshot.model_dump(mode="python"))


def _health_payload(row: SystemHealthSnapshotRow) -> SystemHealthSnapshot:
    """Convert a system health row to a model."""
    return SystemHealthSnapshot(
        health_snapshot_id=row.health_snapshot_id,
        component_name=row.component_name,
        status=row.status,
        metrics_json=row.metrics_json,
        checked_at=row.checked_at,
    )


def _freshness_row(state: DataFreshnessState) -> DataFreshnessStateRow:
    """Convert a freshness state to an ORM row."""
    return DataFreshnessStateRow(**state.model_dump(mode="python"))


def _freshness_payload(row: DataFreshnessStateRow) -> DataFreshnessState:
    """Convert a freshness row to a model."""
    return DataFreshnessState(
        freshness_state_id=row.freshness_state_id,
        dataset_name=row.dataset_name,
        provider_name=row.provider_name,
        latest_available_date=row.latest_available_date,
        latest_fetched_at=row.latest_fetched_at,
        stale_after_seconds=row.stale_after_seconds,
        freshness_status=row.freshness_status,
        checked_at=row.checked_at,
    )


def _redact_payload(value: Any) -> Any:
    """Recursively redact secrets and raw provider payloads."""
    if isinstance(value, dict):
        return {
            key: _REDACTED if _is_sensitive_key(key) else _redact_payload(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_payload(item) for item in value]
    return value


def _is_sensitive_key(key: str) -> bool:
    """Return whether a payload key should be redacted."""
    normalized = key.lower()
    return any(fragment in normalized for fragment in _SENSITIVE_KEY_FRAGMENTS)
