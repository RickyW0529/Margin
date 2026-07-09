"""Tests for formal platform runtime persistence boundaries."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from margin.platform_runtime.db_models import (
    DataFreshnessStateRow,
    DeadLetterQueueRow,
    IdempotencyKeyRow,
    OutboxEventRow,
    RuntimeEnvironmentRow,
    SystemHealthSnapshotRow,
)
from margin.platform_runtime.repository import (
    DataFreshnessState,
    IdempotencyKeyRecord,
    OutboxEvent,
    SQLAlchemyPlatformRuntimeRepository,
    SystemHealthSnapshot,
)
from margin.storage.base import Base
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)


def test_idempotency_record_is_append_only(database_url: str) -> None:
    """Idempotency records should allow exact replay but reject conflicting replay."""
    repository = _repository(database_url)
    expires_at = datetime(2026, 7, 10, tzinfo=UTC)
    record = IdempotencyKeyRecord(
        idempotency_key="idem-platform-1",
        scope="agent_qna",
        request_hash="sha256:request",
        response_hash="sha256:response",
        response_ref="artifact_1",
        status="succeeded",
        expires_at=expires_at,
    )

    repository.record_idempotency_key(record)
    repository.record_idempotency_key(record)

    stored = repository.get_idempotency_key("idem-platform-1")
    assert stored == record

    with pytest.raises(ValueError, match="immutable"):
        repository.record_idempotency_key(
            record.model_copy(update={"response_hash": "sha256:changed"})
        )


def test_outbox_event_retry_updates_attempt_and_next_attempt(database_url: str) -> None:
    """Outbox events should support deterministic claim and retry metadata."""
    repository = _repository(database_url)
    now = datetime(2026, 7, 9, 10, 0, tzinfo=UTC)
    next_attempt = now + timedelta(minutes=5)
    event = OutboxEvent(
        event_id="evt-platform-1",
        aggregate_type="agent_run",
        aggregate_id="run_1",
        event_type="dashboard_projection_ready",
        payload_json={"artifact_id": "artifact_1"},
        status="pending",
        next_attempt_at=now,
    )

    repository.enqueue_outbox_event(event)
    claimed = repository.claim_due_outbox_events(now=now, limit=10)
    assert [item.event_id for item in claimed] == ["evt-platform-1"]

    repository.mark_outbox_retry(
        "evt-platform-1",
        next_attempt_at=next_attempt,
    )

    stored = repository.get_outbox_event("evt-platform-1")
    assert stored is not None
    assert stored.status == "pending"
    assert stored.attempts == 1
    assert stored.next_attempt_at == next_attempt


def test_dead_letter_payload_is_redacted_before_persist(database_url: str) -> None:
    """Dead-letter records must never keep secrets or raw provider payloads."""
    repository = _repository(database_url)

    record = repository.record_dead_letter(
        source_table="platform.outbox_events",
        source_id="evt-platform-2",
        error_code="provider_failed",
        error_message="provider rejected payload",
        payload_json={
            "api_token": "secret-token",
            "raw_text": "full provider response",
            "safe": {"symbol": "000001.SZ"},
        },
    )

    stored = repository.get_dead_letter_record(record.dlq_id)
    assert stored is not None
    assert stored.payload_redacted_json["api_token"] == "[REDACTED]"
    assert stored.payload_redacted_json["raw_text"] == "[REDACTED]"
    assert stored.payload_redacted_json["safe"]["symbol"] == "000001.SZ"


def test_health_and_freshness_snapshots_round_trip(database_url: str) -> None:
    """Ops health and freshness records should be queryable by id."""
    repository = _repository(database_url)
    checked_at = datetime(2026, 7, 9, 10, 0, tzinfo=UTC)
    health = SystemHealthSnapshot(
        health_snapshot_id="health-api-1",
        component_name="api",
        status="healthy",
        metrics_json={"ready": True},
        checked_at=checked_at,
    )
    freshness = DataFreshnessState(
        freshness_state_id="fresh-quote-1",
        dataset_name="daily_quote",
        provider_name="tushare",
        latest_available_date="2026-07-08",
        latest_fetched_at=checked_at,
        freshness_status="current",
        checked_at=checked_at,
    )

    repository.record_system_health_snapshot(health)
    repository.record_data_freshness_state(freshness)

    assert repository.get_system_health_snapshot("health-api-1") == health
    assert repository.get_data_freshness_state("fresh-quote-1") == freshness


def _repository(database_url: str) -> SQLAlchemyPlatformRuntimeRepository:
    """Create a platform repository against the integration-test database."""
    engine = create_database_engine(DatabaseSettings(url=database_url))
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS platform")
        connection.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS ops")
    Base.metadata.drop_all(engine, tables=_platform_tables(), checkfirst=True)
    Base.metadata.create_all(engine)
    return SQLAlchemyPlatformRuntimeRepository(create_session_factory(engine))


def _platform_tables() -> list:
    """Return platform tables in dependency-safe drop order."""
    return [
        DataFreshnessStateRow.__table__,
        SystemHealthSnapshotRow.__table__,
        DeadLetterQueueRow.__table__,
        OutboxEventRow.__table__,
        RuntimeEnvironmentRow.__table__,
        IdempotencyKeyRow.__table__,
    ]
