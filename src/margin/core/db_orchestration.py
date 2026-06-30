"""SQLAlchemy rows for durable orchestration, capacity, outbox, and smoke audit."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from margin.storage.base import Base


class OrchestrationRunRow(Base):
    """Current derived state for a durable business run.

    Attributes:
        run_id: Primary key for the run.
        run_type: Type of the run (e.g. ``valuation_discovery``).
        state: Current derived state of the run.
        scope_version_id: Optional frozen scope version identifier.
        scope_hash: Optional hash of the scope configuration.
        idempotency_key_hash: Optional hash of the idempotency key.
        trace_id: Request trace identifier.
        degradation_reasons: List of degradation reason strings.
        created_at: UTC timestamp when the run was created.
        started_at: UTC timestamp when the run started, if started.
        finished_at: UTC timestamp when the run finished, if finished.
    """

    __tablename__ = "orchestration_runs"
    __table_args__ = (
        Index("ix_orchestration_runs_type_created", "run_type", "created_at"),
        Index("ix_orchestration_runs_state_created", "state", "created_at"),
        Index(
            "uq_orchestration_runs_idempotency",
            "run_type",
            "idempotency_key_hash",
            unique=True,
            postgresql_where="idempotency_key_hash IS NOT NULL",
        ),
    )

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_type: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(48), nullable=False)
    scope_version_id: Mapped[str | None] = mapped_column(String(64))
    scope_hash: Mapped[str | None] = mapped_column(String(96))
    idempotency_key_hash: Mapped[str | None] = mapped_column(String(96))
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    degradation_reasons: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OrchestrationStepAttemptRow(Base):
    """Append-only state event for one execution attempt.

    Attributes:
        event_id: Primary key for the step event.
        run_id: Foreign key to the parent orchestration run.
        step_id: Identifier of the orchestration step.
        attempt_no: Execution attempt number (1-based).
        state_seq: Sequence number for state events within the same attempt.
        state: Current state of the step attempt.
        input_hash: SHA-256 hash of the step input payload.
        input_ref: Optional reference to the input snapshot.
        output_ref: Optional reference to the output snapshot.
        error_code: Optional error code when the step failed.
        retry_after: Optional timestamp when the step may be retried.
        trace_id: Request trace identifier.
        started_at: UTC timestamp when the attempt started.
        finished_at: UTC timestamp when the attempt finished, if finished.
        lease_owner: Optional identifier of the worker holding the lease.
        lease_expires_at: Optional when the current lease expires.
        previous_event_id: Optional id of the preceding step event.
        created_at: UTC timestamp when the event was created.
    """

    __tablename__ = "orchestration_step_attempts"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "step_id",
            "attempt_no",
            "state_seq",
            name="uq_orchestration_step_attempt_sequence",
        ),
        CheckConstraint("attempt_no >= 1", name="ck_step_attempt_positive"),
        CheckConstraint("state_seq >= 0", name="ck_step_state_seq_nonnegative"),
        Index(
            "ix_orchestration_step_claim",
            "state",
            "lease_expires_at",
            "retry_after",
        ),
        Index(
            "ix_orchestration_step_latest",
            "run_id",
            "step_id",
            "attempt_no",
            "state_seq",
        ),
    )

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("orchestration_runs.run_id", ondelete="CASCADE"),
        nullable=False,
    )
    step_id: Mapped[str] = mapped_column(String(96), nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    state_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(48), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(96), nullable=False)
    input_ref: Mapped[str | None] = mapped_column(String(256))
    output_ref: Mapped[str | None] = mapped_column(String(256))
    error_code: Mapped[str | None] = mapped_column(String(96))
    retry_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    previous_event_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CapacityLimitVersionRow(Base):
    """Versioned capacity or budget limit.

    Attributes:
        version_id: Primary key for the limit version.
        limit_key: Key identifying the limit.
        version: Version label for the limit.
        limit_type: Dimension label (``rate``, ``tokens``, ``budget``, ``composite``).
        window_seconds: Duration of the rolling window in seconds.
        max_count: Optional maximum request count per window.
        max_tokens: Optional maximum token count per window.
        max_cost: Optional maximum cumulative cost per window.
        config: Provider-specific configuration dictionary.
        lifecycle: Lifecycle status (``active`` or ``deprecated``).
        created_at: UTC timestamp when the limit was created.
    """

    __tablename__ = "capacity_limit_versions"
    __table_args__ = (
        UniqueConstraint("limit_key", "version", name="uq_capacity_limit_version"),
        Index(
            "uq_active_capacity_limit_key",
            "limit_key",
            unique=True,
            postgresql_where="lifecycle = 'active'",
        ),
        CheckConstraint("window_seconds > 0", name="ck_capacity_window_positive"),
    )

    version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    limit_key: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    limit_type: Mapped[str] = mapped_column(String(32), nullable=False)
    window_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    max_count: Mapped[int | None] = mapped_column(Integer)
    max_tokens: Mapped[int | None] = mapped_column(Integer)
    max_cost: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    lifecycle: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProviderCapacityCounterRow(Base):
    """Persisted usage counter for one limit window.

    Attributes:
        counter_id: Primary key for the counter.
        limit_key: Key identifying the limit.
        limit_version_id: Foreign key to the capacity limit version.
        window_started_at: UTC timestamp when the window started.
        window_ends_at: UTC timestamp when the window ends.
        request_count: Total request count in the window.
        token_count: Total token count in the window.
        cost_amount: Total cumulative cost in the window.
        updated_at: UTC timestamp of the last counter update.
    """

    __tablename__ = "provider_capacity_counters"
    __table_args__ = (
        UniqueConstraint(
            "limit_key",
            "limit_version_id",
            "window_started_at",
            name="uq_provider_capacity_window",
        ),
        CheckConstraint("request_count >= 0", name="ck_capacity_count_nonnegative"),
        CheckConstraint("token_count >= 0", name="ck_capacity_tokens_nonnegative"),
    )

    counter_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    limit_key: Mapped[str] = mapped_column(String(128), nullable=False)
    limit_version_id: Mapped[str] = mapped_column(
        ForeignKey("capacity_limit_versions.version_id"),
        nullable=False,
    )
    window_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    window_ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        default=Decimal("0"),
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TransactionalOutboxRow(Base):
    """Durable event publication record with idempotency and lease state.

    Attributes:
        outbox_id: Primary key for the outbox message.
        topic: Message topic used for routing.
        idempotency_key: Key for deduplicating repeated enqueue requests.
        payload: JSONB message payload.
        state: Current delivery state of the message.
        available_at: Timestamp when the message becomes claimable.
        lease_owner: Optional identifier of the worker holding the lease.
        lease_expires_at: Optional when the current lease expires.
        attempt_count: Number of delivery attempts made so far.
        last_error_code: Error code from the last failed attempt.
        created_at: UTC timestamp when the message was created.
        delivered_at: UTC timestamp when the message was delivered, if done.
    """

    __tablename__ = "transactional_outbox"
    __table_args__ = (
        UniqueConstraint("topic", "idempotency_key", name="uq_outbox_topic_idempotency"),
        CheckConstraint("attempt_count >= 0", name="ck_outbox_attempt_nonnegative"),
        Index(
            "ix_transactional_outbox_claim",
            "topic",
            "state",
            "available_at",
        ),
    )

    outbox_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    topic: Mapped[str] = mapped_column(String(128), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(192), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    state: Mapped[str] = mapped_column(String(48), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error_code: Mapped[str | None] = mapped_column(String(96))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
