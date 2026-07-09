"""Transactional outbox idempotency, lease, and recovery tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete

from margin.core.db_orchestration import OrchestrationRunRow, TransactionalOutboxRow
from margin.core.outbox import (
    MemoryOutboxRepository,
    OutboxState,
    SQLAlchemyOutboxRepository,
    TransactionalOutbox,
)
from margin.storage.base import Base
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)


def _now() -> datetime:
    """Return a fixed datetime for test determinism.

    Returns:
        datetime: .
    """
    return datetime(2026, 6, 22, 12, 0, tzinfo=UTC)


def test_outbox_enqueue_is_idempotent() -> None:
    """Test that outbox enqueue is idempotent.

    Returns:
        None: .
    """
    repository = MemoryOutboxRepository()
    outbox = TransactionalOutbox(repository, clock=_now)

    first = outbox.enqueue_once(
        topic="research_delta_published",
        idempotency_key="graph-1:published",
        payload={"graph_run_id": "graph-1"},
    )
    replay = outbox.enqueue_once(
        topic="research_delta_published",
        idempotency_key="graph-1:published",
        payload={"graph_run_id": "graph-1"},
    )

    assert replay.outbox_id == first.outbox_id
    assert repository.count_topic("research_delta_published") == 1


def test_outbox_reclaims_expired_lease_and_requires_owner_to_ack() -> None:
    """Test that expired leases are reclaimed and only the owner can ack.

    Returns:
        None: .
    """
    repository = MemoryOutboxRepository()
    outbox = TransactionalOutbox(repository, clock=_now)
    queued = outbox.enqueue_once(
        topic="vector_index",
        idempotency_key="document-1:index",
        payload={"event_id": "document-1"},
    )

    first_claim = outbox.claim_batch(
        topic="vector_index",
        worker_id="worker-old",
        lease_seconds=30,
        limit=1,
    )
    assert first_claim[0].outbox_id == queued.outbox_id
    assert (
        outbox.claim_batch(
            topic="vector_index",
            worker_id="worker-new",
            lease_seconds=30,
            limit=1,
        )
        == []
    )

    reclaimed = outbox.claim_batch(
        topic="vector_index",
        worker_id="worker-new",
        lease_seconds=30,
        limit=1,
        now=_now() + timedelta(seconds=31),
    )

    assert reclaimed[0].attempt_count == 2
    assert outbox.mark_delivered(queued.outbox_id, worker_id="worker-old") is False
    assert outbox.mark_delivered(queued.outbox_id, worker_id="worker-new") is True
    assert repository.get(queued.outbox_id).state == OutboxState.DELIVERED


def test_postgres_outbox_is_idempotent_and_recoverable(database_url: str) -> None:
    """Test that the PostgreSQL outbox is idempotent and recoverable.

    Args:
        database_url: str: .

    Returns:
        None: .
    """
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    topic = "test-v02-outbox"
    with session_factory.begin() as session:
        session.execute(delete(TransactionalOutboxRow).where(TransactionalOutboxRow.topic == topic))
    outbox = TransactionalOutbox(
        SQLAlchemyOutboxRepository(session_factory),
        clock=_now,
    )

    try:
        first = outbox.enqueue_once(
            topic=topic,
            idempotency_key="event-1",
            payload={"event_id": "event-1"},
        )
        replay = outbox.enqueue_once(
            topic=topic,
            idempotency_key="event-1",
            payload={"event_id": "event-1"},
        )
        assert replay.outbox_id == first.outbox_id

        claimed = outbox.claim_batch(
            topic=topic,
            worker_id="worker-1",
            lease_seconds=30,
            limit=10,
        )
        assert len(claimed) == 1
        assert outbox.mark_failed(
            first.outbox_id,
            worker_id="worker-1",
            error_code="downstream_timeout",
            retry_after=_now() + timedelta(seconds=10),
        )

        assert (
            outbox.claim_batch(
                topic=topic,
                worker_id="worker-2",
                lease_seconds=30,
                limit=10,
                now=_now() + timedelta(seconds=9),
            )
            == []
        )
        assert (
            len(
                outbox.claim_batch(
                    topic=topic,
                    worker_id="worker-2",
                    lease_seconds=30,
                    limit=10,
                    now=_now() + timedelta(seconds=10),
                )
            )
            == 1
        )
    finally:
        with session_factory.begin() as session:
            session.execute(
                delete(TransactionalOutboxRow).where(TransactionalOutboxRow.topic == topic)
            )
        engine.dispose()


def test_postgres_outbox_joins_business_transaction_and_rolls_back(
    database_url: str,
) -> None:
    """Test that the PostgreSQL outbox joins business transactions and rolls back.

    Args:
        database_url: str: .

    Returns:
        None: .
    """
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    topic = "test-v02-transactional-outbox"
    run_id = "run-outbox-rollback"
    repository = SQLAlchemyOutboxRepository(session_factory)
    with session_factory.begin() as session:
        session.execute(delete(TransactionalOutboxRow).where(TransactionalOutboxRow.topic == topic))
        session.execute(delete(OrchestrationRunRow).where(OrchestrationRunRow.run_id == run_id))

    try:
        with pytest.raises(RuntimeError, match="force rollback"):
            with session_factory.begin() as session:
                session.add(
                    OrchestrationRunRow(
                        run_id=run_id,
                        run_type="valuation_discovery",
                        state="running",
                        trace_id="trace-outbox-rollback",
                        degradation_reasons=[],
                        created_at=_now(),
                        started_at=_now(),
                    )
                )
                repository.enqueue_once_in_session(
                    session,
                    topic=topic,
                    idempotency_key="run-created",
                    payload={"run_id": run_id},
                    now=_now(),
                )
                raise RuntimeError("force rollback")

        with session_factory() as session:
            assert session.get(OrchestrationRunRow, run_id) is None
        assert repository.count_topic(topic) == 0
    finally:
        with session_factory.begin() as session:
            session.execute(
                delete(TransactionalOutboxRow).where(TransactionalOutboxRow.topic == topic)
            )
            session.execute(delete(OrchestrationRunRow).where(OrchestrationRunRow.run_id == run_id))
        engine.dispose()
