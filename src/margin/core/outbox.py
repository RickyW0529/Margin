"""Generic transactional outbox with idempotency, leases, and retry states."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from threading import RLock
from typing import Any, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from margin.core.db_orchestration import TransactionalOutboxRow


def _utc_now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(UTC)


class OutboxState(StrEnum):
    """States of a transactional outbox message."""

    PENDING = "pending"
    CLAIMED = "claimed"
    DELIVERED = "delivered"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_FINAL = "failed_final"


class OutboxMessage(BaseModel):
    """Sanitized outbox message and current delivery state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    outbox_id: str
    topic: str
    idempotency_key: str
    payload: dict[str, Any]
    state: OutboxState
    available_at: datetime
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    attempt_count: int = Field(ge=0)
    last_error_code: str | None = None
    created_at: datetime
    delivered_at: datetime | None = None


class OutboxRepository(Protocol):
    """Persistence contract for durable outbox messages."""

    def enqueue_once(
        self,
        *,
        topic: str,
        idempotency_key: str,
        payload: dict[str, Any],
        now: datetime,
    ) -> OutboxMessage:
        """Enqueue a message with idempotency checking."""
        ...

    def claim_batch(
        self,
        *,
        topic: str,
        worker_id: str,
        now: datetime,
        lease_expires_at: datetime,
        limit: int,
    ) -> list[OutboxMessage]:
        """Claim a batch of due messages for delivery."""
        ...

    def mark_delivered(self, outbox_id: str, *, worker_id: str, now: datetime) -> bool:
        """Mark a claimed message as delivered."""
        ...

    def mark_failed(
        self,
        outbox_id: str,
        *,
        worker_id: str,
        error_code: str,
        retry_after: datetime | None,
    ) -> bool:
        """Mark a claimed message as failed, optionally retryable."""
        ...

    def get(self, outbox_id: str) -> OutboxMessage | None:
        """Retrieve an outbox message by its identifier."""
        ...

    def count_topic(self, topic: str) -> int:
        """Return the total number of messages for a topic."""
        ...


class MemoryOutboxRepository:
    """Thread-safe in-memory implementation of the outbox contract."""

    def __init__(self) -> None:
        """Initialize an empty in-memory outbox."""
        self._lock = RLock()
        self._rows: dict[str, OutboxMessage] = {}
        self._keys: dict[tuple[str, str], str] = {}

    def enqueue_once(
        self,
        *,
        topic: str,
        idempotency_key: str,
        payload: dict[str, Any],
        now: datetime,
    ) -> OutboxMessage:
        """Enqueue a message with idempotency checking.

        Args:
            topic: Message topic.
            idempotency_key: Key for deduplication.
            payload: The message payload.
            now: Current timestamp.

        Returns:
            The existing or newly created OutboxMessage.

        Raises:
            ValueError: If the idempotency key exists with a conflicting payload.
        """
        with self._lock:
            key = (topic, idempotency_key)
            existing_id = self._keys.get(key)
            if existing_id is not None:
                existing = self._rows[existing_id]
                if existing.payload != payload:
                    raise ValueError("outbox idempotency key has conflicting payload")
                return existing
            message = OutboxMessage(
                outbox_id=f"outbox_{uuid4().hex}",
                topic=topic,
                idempotency_key=idempotency_key,
                payload=dict(payload),
                state=OutboxState.PENDING,
                available_at=now,
                attempt_count=0,
                created_at=now,
            )
            self._rows[message.outbox_id] = message
            self._keys[key] = message.outbox_id
            return message

    def claim_batch(
        self,
        *,
        topic: str,
        worker_id: str,
        now: datetime,
        lease_expires_at: datetime,
        limit: int,
    ) -> list[OutboxMessage]:
        """Claim a batch of due messages with lease assignment.

        Args:
            topic: Message topic.
            worker_id: Identifier of the claiming worker.
            now: Current timestamp.
            lease_expires_at: When the lease expires.
            limit: Maximum number of messages to claim.

        Returns:
            List of claimed OutboxMessages.
        """
        with self._lock:
            candidates = sorted(
                (
                    row
                    for row in self._rows.values()
                    if row.topic == topic and _outbox_claimable(row, now)
                ),
                key=lambda row: (row.available_at, row.created_at, row.outbox_id),
            )[:limit]
            claimed: list[OutboxMessage] = []
            for row in candidates:
                updated = row.model_copy(
                    update={
                        "state": OutboxState.CLAIMED,
                        "lease_owner": worker_id,
                        "lease_expires_at": lease_expires_at,
                        "attempt_count": row.attempt_count + 1,
                    }
                )
                self._rows[row.outbox_id] = updated
                claimed.append(updated)
            return claimed

    def mark_delivered(self, outbox_id: str, *, worker_id: str, now: datetime) -> bool:
        """Mark a claimed message as delivered.

        Args:
            outbox_id: Identifier of the message.
            worker_id: Identifier of the claiming worker.
            now: Current timestamp.

        Returns:
            True if the message was marked delivered, False otherwise.
        """
        with self._lock:
            row = self._rows.get(outbox_id)
            if (
                row is None
                or row.state != OutboxState.CLAIMED
                or row.lease_owner != worker_id
            ):
                return False
            self._rows[outbox_id] = row.model_copy(
                update={
                    "state": OutboxState.DELIVERED,
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "delivered_at": now,
                }
            )
            return True

    def mark_failed(
        self,
        outbox_id: str,
        *,
        worker_id: str,
        error_code: str,
        retry_after: datetime | None,
    ) -> bool:
        """Mark a claimed message as failed.

        Args:
            outbox_id: Identifier of the message.
            worker_id: Identifier of the claiming worker.
            error_code: Reason for the failure.
            retry_after: Optional retry time for retryable failures.

        Returns:
            True if the message was marked failed, False otherwise.
        """
        with self._lock:
            row = self._rows.get(outbox_id)
            if (
                row is None
                or row.state != OutboxState.CLAIMED
                or row.lease_owner != worker_id
            ):
                return False
            state = (
                OutboxState.FAILED_RETRYABLE
                if retry_after is not None
                else OutboxState.FAILED_FINAL
            )
            self._rows[outbox_id] = row.model_copy(
                update={
                    "state": state,
                    "available_at": retry_after or row.available_at,
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "last_error_code": error_code,
                }
            )
            return True

    def get(self, outbox_id: str) -> OutboxMessage | None:
        """Retrieve an outbox message by identifier.

        Args:
            outbox_id: The message identifier.

        Returns:
            The OutboxMessage, or None if not found.
        """
        with self._lock:
            return self._rows.get(outbox_id)

    def count_topic(self, topic: str) -> int:
        """Return the total number of messages for a topic.

        Args:
            topic: The topic to count.

        Returns:
            Message count for the topic.
        """
        with self._lock:
            return sum(row.topic == topic for row in self._rows.values())


class SQLAlchemyOutboxRepository:
    """PostgreSQL outbox repository using unique keys and ``SKIP LOCKED``."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        """Initialize the repository.

        Args:
            session_factory: Callable that returns a new SQLAlchemy session.
        """
        self._session_factory = session_factory

    def enqueue_once(
        self,
        *,
        topic: str,
        idempotency_key: str,
        payload: dict[str, Any],
        now: datetime,
    ) -> OutboxMessage:
        """Enqueue a message with idempotency checking.

        Args:
            topic: Message topic.
            idempotency_key: Key for deduplication.
            payload: The message payload.
            now: Current timestamp.

        Returns:
            The existing or newly created OutboxMessage.
        """
        with self._session_factory.begin() as session:
            return self.enqueue_once_in_session(
                session,
                topic=topic,
                idempotency_key=idempotency_key,
                payload=payload,
                now=now,
            )

    def enqueue_once_in_session(
        self,
        session: Session,
        *,
        topic: str,
        idempotency_key: str,
        payload: dict[str, Any],
        now: datetime,
    ) -> OutboxMessage:
        """Enqueue using the caller's business transaction."""
        outbox_id = f"outbox_{uuid4().hex}"
        session.execute(
            insert(TransactionalOutboxRow)
            .values(
                outbox_id=outbox_id,
                topic=topic,
                idempotency_key=idempotency_key,
                payload=payload,
                state=OutboxState.PENDING.value,
                available_at=now,
                attempt_count=0,
                created_at=now,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    TransactionalOutboxRow.topic,
                    TransactionalOutboxRow.idempotency_key,
                ]
            )
        )
        row = session.scalar(
            select(TransactionalOutboxRow).where(
                TransactionalOutboxRow.topic == topic,
                TransactionalOutboxRow.idempotency_key == idempotency_key,
            )
        )
        if row is None:
            raise RuntimeError("outbox row could not be created")
        if dict(row.payload) != payload:
            raise ValueError("outbox idempotency key has conflicting payload")
        return _outbox_from_row(row)

    def claim_batch(
        self,
        *,
        topic: str,
        worker_id: str,
        now: datetime,
        lease_expires_at: datetime,
        limit: int,
    ) -> list[OutboxMessage]:
        """Claim a batch of due messages using SKIP LOCKED.

        Args:
            topic: Message topic.
            worker_id: Identifier of the claiming worker.
            now: Current timestamp.
            lease_expires_at: When the lease expires.
            limit: Maximum number of messages to claim.

        Returns:
            List of claimed OutboxMessages.
        """
        claimable = or_(
            and_(
                TransactionalOutboxRow.state.in_(
                    [
                        OutboxState.PENDING.value,
                        OutboxState.FAILED_RETRYABLE.value,
                    ]
                ),
                TransactionalOutboxRow.available_at <= now,
            ),
            and_(
                TransactionalOutboxRow.state == OutboxState.CLAIMED.value,
                TransactionalOutboxRow.lease_expires_at <= now,
            ),
        )
        statement = (
            select(TransactionalOutboxRow)
            .where(TransactionalOutboxRow.topic == topic, claimable)
            .order_by(
                TransactionalOutboxRow.available_at,
                TransactionalOutboxRow.created_at,
                TransactionalOutboxRow.outbox_id,
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        with self._session_factory.begin() as session:
            rows = session.scalars(statement).all()
            result: list[OutboxMessage] = []
            for row in rows:
                row.state = OutboxState.CLAIMED.value
                row.lease_owner = worker_id
                row.lease_expires_at = lease_expires_at
                row.attempt_count += 1
                result.append(_outbox_from_row(row))
            return result

    def mark_delivered(self, outbox_id: str, *, worker_id: str, now: datetime) -> bool:
        """Mark a claimed message as delivered.

        Args:
            outbox_id: Identifier of the message.
            worker_id: Identifier of the claiming worker.
            now: Current timestamp.

        Returns:
            True if the message was marked delivered, False otherwise.
        """
        with self._session_factory.begin() as session:
            row = session.get(TransactionalOutboxRow, outbox_id)
            if (
                row is None
                or row.state != OutboxState.CLAIMED.value
                or row.lease_owner != worker_id
            ):
                return False
            row.state = OutboxState.DELIVERED.value
            row.lease_owner = None
            row.lease_expires_at = None
            row.delivered_at = now
            return True

    def mark_failed(
        self,
        outbox_id: str,
        *,
        worker_id: str,
        error_code: str,
        retry_after: datetime | None,
    ) -> bool:
        """Mark a claimed message as failed.

        Args:
            outbox_id: Identifier of the message.
            worker_id: Identifier of the claiming worker.
            error_code: Reason for the failure.
            retry_after: Optional retry time for retryable failures.

        Returns:
            True if the message was marked failed, False otherwise.
        """
        with self._session_factory.begin() as session:
            row = session.get(TransactionalOutboxRow, outbox_id)
            if (
                row is None
                or row.state != OutboxState.CLAIMED.value
                or row.lease_owner != worker_id
            ):
                return False
            row.state = (
                OutboxState.FAILED_RETRYABLE.value
                if retry_after is not None
                else OutboxState.FAILED_FINAL.value
            )
            if retry_after is not None:
                row.available_at = retry_after
            row.lease_owner = None
            row.lease_expires_at = None
            row.last_error_code = error_code
            return True

    def get(self, outbox_id: str) -> OutboxMessage | None:
        """Retrieve an outbox message by identifier.

        Args:
            outbox_id: The message identifier.

        Returns:
            The OutboxMessage, or None if not found.
        """
        with self._session_factory() as session:
            row = session.get(TransactionalOutboxRow, outbox_id)
            return _outbox_from_row(row) if row is not None else None

    def count_topic(self, topic: str) -> int:
        """Return the total number of messages for a topic.

        Args:
            topic: The topic to count.

        Returns:
            Message count for the topic.
        """
        with self._session_factory() as session:
            return int(
                session.scalar(
                    select(func.count())
                    .select_from(TransactionalOutboxRow)
                    .where(TransactionalOutboxRow.topic == topic)
                )
                or 0
            )


class TransactionalOutbox:
    """Validated facade over a durable outbox repository."""

    def __init__(
        self,
        repository: OutboxRepository,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        """Initialize the outbox facade.

        Args:
            repository: The outbox repository.
            clock: Callable returning current UTC time.
        """
        self._repository = repository
        self._clock = clock

    def enqueue_once(
        self,
        *,
        topic: str,
        idempotency_key: str,
        payload: dict[str, Any],
    ) -> OutboxMessage:
        """Enqueue a message with validation and idempotency.

        Args:
            topic: Message topic.
            idempotency_key: Key for deduplication.
            payload: The message payload.

        Returns:
            The existing or newly created OutboxMessage.

        Raises:
            ValueError: If topic or idempotency_key is empty.
        """
        if not topic.strip() or not idempotency_key.strip():
            raise ValueError("topic and idempotency_key are required")
        return self._repository.enqueue_once(
            topic=topic,
            idempotency_key=idempotency_key,
            payload=payload,
            now=self._clock(),
        )

    def claim_batch(
        self,
        *,
        topic: str,
        worker_id: str,
        lease_seconds: int,
        limit: int,
        now: datetime | None = None,
    ) -> list[OutboxMessage]:
        """Claim a batch of due messages.

        Args:
            topic: Message topic.
            worker_id: Identifier of the claiming worker.
            lease_seconds: Lease duration in seconds.
            limit: Maximum number of messages to claim.
            now: Current timestamp (uses clock if not provided).

        Returns:
            List of claimed OutboxMessages.

        Raises:
            ValueError: If lease_seconds or limit is not positive.
        """
        claimed_at = now or self._clock()
        if lease_seconds <= 0 or limit <= 0:
            raise ValueError("lease_seconds and limit must be positive")
        return self._repository.claim_batch(
            topic=topic,
            worker_id=worker_id,
            now=claimed_at,
            lease_expires_at=claimed_at + timedelta(seconds=lease_seconds),
            limit=limit,
        )

    def mark_delivered(self, outbox_id: str, *, worker_id: str) -> bool:
        """Mark a message as delivered.

        Args:
            outbox_id: Identifier of the message.
            worker_id: Identifier of the claiming worker.

        Returns:
            True if the message was marked delivered.
        """
        return self._repository.mark_delivered(
            outbox_id,
            worker_id=worker_id,
            now=self._clock(),
        )

    def mark_failed(
        self,
        outbox_id: str,
        *,
        worker_id: str,
        error_code: str,
        retry_after: datetime | None,
    ) -> bool:
        """Mark a message as failed.

        Args:
            outbox_id: Identifier of the message.
            worker_id: Identifier of the claiming worker.
            error_code: Reason for the failure.
            retry_after: Optional retry time for retryable failures.

        Returns:
            True if the message was marked failed.
        """
        return self._repository.mark_failed(
            outbox_id,
            worker_id=worker_id,
            error_code=error_code,
            retry_after=retry_after,
        )


def _outbox_claimable(row: OutboxMessage, now: datetime) -> bool:
    """Determine whether an outbox message is eligible for claiming.

    A message is claimable if it is pending or failed-retryable and past its
    available_at, or if it is claimed but its lease has expired.

    Args:
        row: The outbox message to check.
        now: Current timestamp.

    Returns:
        True if the message can be claimed.
    """
    if row.state in {OutboxState.PENDING, OutboxState.FAILED_RETRYABLE}:
        return row.available_at <= now
    return (
        row.state == OutboxState.CLAIMED
        and row.lease_expires_at is not None
        and row.lease_expires_at <= now
    )


def _outbox_from_row(row: TransactionalOutboxRow) -> OutboxMessage:
    """Map a transactional outbox ORM row to a domain model.

    Args:
        row: The outbox ORM row.

    Returns:
        The corresponding domain OutboxMessage.
    """
    return OutboxMessage(
        outbox_id=row.outbox_id,
        topic=row.topic,
        idempotency_key=row.idempotency_key,
        payload=dict(row.payload),
        state=OutboxState(row.state),
        available_at=row.available_at,
        lease_owner=row.lease_owner,
        lease_expires_at=row.lease_expires_at,
        attempt_count=row.attempt_count,
        last_error_code=row.last_error_code,
        created_at=row.created_at,
        delivered_at=row.delivered_at,
    )
