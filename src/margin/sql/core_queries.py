"""Core infrastructure query factory (outbox, capacity, audit, orchestration)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Select, and_, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import aliased

from margin.core.db_audit import AuditLogRecordRow
from margin.core.db_orchestration import (
    CapacityLimitVersionRow,
    OrchestrationRunRow,
    OrchestrationStepAttemptRow,
    ProviderCapacityCounterRow,
    TransactionalOutboxRow,
)
from margin.core.run_states import StepState
from margin.strategy.db_models import ProviderSecretVersionRow


def outbox_row_by_topic_and_key(
    topic: str,
    idempotency_key: str,
) -> Select:
    """Return an outbox row by topic and idempotency key.

    Args:
        topic: str: .
        idempotency_key: str: .

    Returns:
        Select: .
    """
    return select(TransactionalOutboxRow).where(
        TransactionalOutboxRow.topic == topic,
        TransactionalOutboxRow.idempotency_key == idempotency_key,
    )


def outbox_claim_batch(
    topic: str,
    now: datetime,
    limit: int,
) -> Select:
    """Return claimable outbox rows for a topic using SKIP LOCKED.

    Args:
        topic: str: .
        now: datetime: .
        limit: int: .

    Returns:
        Select: .
    """
    claimable = or_(
        and_(
            TransactionalOutboxRow.state.in_(
                [
                    "pending",
                    "failed_retryable",
                ]
            ),
            TransactionalOutboxRow.available_at <= now,
        ),
        and_(
            TransactionalOutboxRow.state == "claimed",
            TransactionalOutboxRow.lease_expires_at <= now,
        ),
    )
    return (
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


def outbox_count_by_topic(topic: str) -> Select:
    """Return a count query for outbox messages by topic.

    Args:
        topic: str: .

    Returns:
        Select: .
    """
    return (
        select(func.count())
        .select_from(TransactionalOutboxRow)
        .where(TransactionalOutboxRow.topic == topic)
    )


def insert_outbox_row(
    *,
    outbox_id: str,
    topic: str,
    idempotency_key: str,
    payload: dict[str, Any],
    state: str,
    available_at: datetime,
    now: datetime,
) -> Any:
    """Insert one outbox row with idempotency conflict handling.

    Args:
        outbox_id: str: .
        topic: str: .
        idempotency_key: str: .
        payload: dict[str, Any]: .
        state: str: .
        available_at: datetime: .
        now: datetime: .

    Returns:
        Any: .
    """
    return (
        insert(TransactionalOutboxRow)
        .values(
            outbox_id=outbox_id,
            topic=topic,
            idempotency_key=idempotency_key,
            payload=payload,
            state=state,
            available_at=available_at,
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


def active_capacity_limit(limit_key: str) -> Select:
    """Return the active capacity limit for a given key.

    Args:
        limit_key: str: .

    Returns:
        Select: .
    """
    return (
        select(CapacityLimitVersionRow)
        .where(
            CapacityLimitVersionRow.limit_key == limit_key,
            CapacityLimitVersionRow.lifecycle == "active",
        )
        .order_by(CapacityLimitVersionRow.created_at.desc())
        .limit(1)
    )


def deprecate_active_limits(limit_key: str) -> Any:
    """Deprecate all active limits for a given key.

    Args:
        limit_key: str: .

    Returns:
        Any: .
    """
    return (
        update(CapacityLimitVersionRow)
        .where(
            CapacityLimitVersionRow.limit_key == limit_key,
            CapacityLimitVersionRow.lifecycle == "active",
        )
        .values(lifecycle="deprecated")
    )


def insert_capacity_counter(
    *,
    counter_id: str,
    limit_key: str,
    limit_version_id: str,
    window_started_at: datetime,
    window_ends_at: datetime,
) -> Any:
    """Insert one capacity counter row with conflict handling.

    Args:
        counter_id: str: .
        limit_key: str: .
        limit_version_id: str: .
        window_started_at: datetime: .
        window_ends_at: datetime: .

    Returns:
        Any: .
    """
    from decimal import Decimal

    return (
        insert(ProviderCapacityCounterRow)
        .values(
            counter_id=counter_id,
            limit_key=limit_key,
            limit_version_id=limit_version_id,
            window_started_at=window_started_at,
            window_ends_at=window_ends_at,
            request_count=0,
            token_count=0,
            cost_amount=Decimal("0"),
            updated_at=window_started_at,
        )
        .on_conflict_do_nothing(
            index_elements=[
                ProviderCapacityCounterRow.limit_key,
                ProviderCapacityCounterRow.limit_version_id,
                ProviderCapacityCounterRow.window_started_at,
            ]
        )
    )


def capacity_counter_for_update(
    limit_key: str,
    limit_version_id: str,
    window_started_at: datetime,
) -> Select:
    """Return a capacity counter row locked for update.

    Args:
        limit_key: str: .
        limit_version_id: str: .
        window_started_at: datetime: .

    Returns:
        Select: .
    """
    return (
        select(ProviderCapacityCounterRow)
        .where(
            ProviderCapacityCounterRow.limit_key == limit_key,
            ProviderCapacityCounterRow.limit_version_id == limit_version_id,
            ProviderCapacityCounterRow.window_started_at == window_started_at,
        )
        .with_for_update()
    )


def secret_by_idempotency(
    provider_name: str,
    secret_name: str,
    idempotency_key: str,
) -> Select:
    """Return a secret version row by provider, name, and idempotency key.

    Args:
        provider_name: str: .
        secret_name: str: .
        idempotency_key: str: .

    Returns:
        Select: .
    """
    return (
        select(ProviderSecretVersionRow)
        .where(ProviderSecretVersionRow.provider_name == provider_name)
        .where(ProviderSecretVersionRow.secret_name == secret_name)
        .where(ProviderSecretVersionRow.idempotency_key == idempotency_key)
    )


def active_secrets_by_provider_and_name(
    provider_name: str,
    secret_name: str,
) -> Select:
    """Return active secret rows for a provider and name.

    Args:
        provider_name: str: .
        secret_name: str: .

    Returns:
        Select: .
    """
    return (
        select(ProviderSecretVersionRow)
        .where(ProviderSecretVersionRow.provider_name == provider_name)
        .where(ProviderSecretVersionRow.secret_name == secret_name)
        .where(ProviderSecretVersionRow.status == "active")
    )


def secrets_list(
    provider_name: str | None = None,
    secret_name: str | None = None,
) -> Select:
    """Return secret rows in creation order without decrypting them.

    Args:
        provider_name: str | None: .
        secret_name: str | None: .

    Returns:
        Select: .
    """
    query = select(ProviderSecretVersionRow)
    if provider_name is not None:
        query = query.where(ProviderSecretVersionRow.provider_name == provider_name)
    if secret_name is not None:
        query = query.where(ProviderSecretVersionRow.secret_name == secret_name)
    return query.order_by(ProviderSecretVersionRow.created_at)


def audit_records(
    record_type: str | None = None,
    object_id: str | None = None,
    trace_id: str | None = None,
    limit: int = 100,
) -> Select:
    """Return audit records ordered by recorded_at desc with optional filters.

    Args:
        record_type: str | None: .
        object_id: str | None: .
        trace_id: str | None: .
        limit: int: .

    Returns:
        Select: .
    """
    statement = select(AuditLogRecordRow).order_by(AuditLogRecordRow.recorded_at.desc())
    if record_type is not None:
        statement = statement.where(AuditLogRecordRow.record_type == record_type)
    if object_id is not None:
        statement = statement.where(AuditLogRecordRow.object_id == object_id)
    if trace_id is not None:
        statement = statement.where(AuditLogRecordRow.trace_id == trace_id)
    return statement.limit(limit)


def orchestration_runs(
    run_type: str | None = None,
    scope_version_id: str | None = None,
    state_value: str | None = None,
    limit: int = 50,
) -> Select:
    """Return persisted runs, newest first, filtered by optional facets.

    Args:
        run_type: str | None: .
        scope_version_id: str | None: .
        state_value: str | None: .
        limit: int: .

    Returns:
        Select: .
    """
    clause = []
    if run_type is not None:
        clause.append(OrchestrationRunRow.run_type == run_type)
    if scope_version_id is not None:
        clause.append(OrchestrationRunRow.scope_version_id == scope_version_id)
    if state_value is not None:
        clause.append(OrchestrationRunRow.state == state_value)
    statement = select(OrchestrationRunRow)
    if clause:
        statement = statement.where(and_(*clause))
    return statement.order_by(
        OrchestrationRunRow.created_at.desc(),
        OrchestrationRunRow.run_id.desc(),
    ).limit(limit)


def step_event_by_sequence(
    run_id: str,
    step_id: str,
    attempt_no: int,
    state_seq: int,
) -> Select:
    """Return a step event ID by its unique sequence key.

    Args:
        run_id: str: .
        step_id: str: .
        attempt_no: int: .
        state_seq: int: .

    Returns:
        Select: .
    """
    return select(OrchestrationStepAttemptRow.event_id).where(
        OrchestrationStepAttemptRow.run_id == run_id,
        OrchestrationStepAttemptRow.step_id == step_id,
        OrchestrationStepAttemptRow.attempt_no == attempt_no,
        OrchestrationStepAttemptRow.state_seq == state_seq,
    )


def step_events_by_run_and_step(
    run_id: str,
    step_id: str,
) -> Select:
    """Return all step events for a run and step ordered by sequence.

    Args:
        run_id: str: .
        step_id: str: .

    Returns:
        Select: .
    """
    return (
        select(OrchestrationStepAttemptRow)
        .where(
            OrchestrationStepAttemptRow.run_id == run_id,
            OrchestrationStepAttemptRow.step_id == step_id,
        )
        .order_by(
            OrchestrationStepAttemptRow.attempt_no,
            OrchestrationStepAttemptRow.state_seq,
            OrchestrationStepAttemptRow.created_at,
        )
    )


def latest_step_event(
    run_id: str,
    step_id: str,
) -> Select:
    """Return the most recent step event for a run and step.

    Args:
        run_id: str: .
        step_id: str: .

    Returns:
        Select: .
    """
    return (
        select(OrchestrationStepAttemptRow)
        .where(
            OrchestrationStepAttemptRow.run_id == run_id,
            OrchestrationStepAttemptRow.step_id == step_id,
        )
        .order_by(
            OrchestrationStepAttemptRow.attempt_no.desc(),
            OrchestrationStepAttemptRow.state_seq.desc(),
            OrchestrationStepAttemptRow.created_at.desc(),
        )
        .limit(1)
    )


def claim_next_step_statement(
    now: datetime,
    allowed_step_ids: frozenset[str] | None = None,
) -> Select:
    """Return a claimable step event using a PostgreSQL row lock.

    Args:
        now: datetime: .
        allowed_step_ids: frozenset[str] | None: .

    Returns:
        Select: .
    """
    current = OrchestrationStepAttemptRow
    newer = aliased(OrchestrationStepAttemptRow)
    has_newer = exists(
        select(newer.event_id).where(
            newer.run_id == current.run_id,
            newer.step_id == current.step_id,
            or_(
                newer.attempt_no > current.attempt_no,
                and_(
                    newer.attempt_no == current.attempt_no,
                    newer.state_seq > current.state_seq,
                ),
            ),
        )
    )
    due_retry = or_(current.retry_after.is_(None), current.retry_after <= now)
    claimable = or_(
        current.state == StepState.PENDING.value,
        and_(current.state == StepState.FAILED_RETRYABLE.value, due_retry),
        and_(
            current.state.in_(
                [
                    StepState.WAITING_RATE_LIMIT.value,
                    StepState.WAITING_BUDGET.value,
                ]
            ),
            due_retry,
        ),
        and_(
            current.state == StepState.RUNNING.value,
            current.lease_expires_at.is_not(None),
            current.lease_expires_at <= now,
        ),
    )
    statement = (
        select(current)
        .where(~has_newer, claimable)
        .order_by(current.created_at, current.run_id, current.step_id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if allowed_step_ids is not None:
        statement = statement.where(current.step_id.in_(allowed_step_ids))
    return statement
