"""Durable v0.2 news target queue tests."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest

from margin.news.db_models import (
    DocumentMaterialityScoreRow,
    DocumentSecurityLinkRow,
    NewsContextBundleRow,
    NewsContextDocumentRow,
    NewsRefreshRunRow,
    NewsRefreshTargetRow,
)
from margin.news.models import NewsTarget, NewsTargetStatus, TargetTriggerType
from margin.news.repository import NewsRepository
from margin.news.target_queue import NewsTargetQueue, TargetReconciliation
from margin.storage.base import Base
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)


@pytest.fixture
def news_repository(database_url: str) -> Iterator[NewsRepository]:
    """Create a clean repository with the v0.2 news refresh tables.

    Args:
        database_url: str: .

    Yields:
        Any: .
    """
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    with session_factory.begin() as session:
        for row in (
            NewsContextDocumentRow,
            NewsContextBundleRow,
            DocumentMaterialityScoreRow,
            DocumentSecurityLinkRow,
            NewsRefreshTargetRow,
            NewsRefreshRunRow,
        ):
            session.query(row).delete()
    yield NewsRepository(session_factory)
    engine.dispose()


def make_target(symbol: str, priority: int = 10) -> NewsTarget:
    """Build a deterministic queue target fixture.

    Args:
        symbol: str: .
        priority: int: .

    Returns:
        NewsTarget: .
    """
    return NewsTarget(
        scope_version_id="scope-1",
        quant_run_id="quant-1",
        security_id=f"{symbol}.SZ",
        symbol=symbol,
        name=f"公司{symbol}",
        trigger_type=TargetTriggerType.NEW_PASS,
        decision_at=datetime(2026, 6, 22, tzinfo=UTC),
        priority=priority,
    )


def test_enqueue_all_is_complete_and_idempotent(news_repository: NewsRepository) -> None:
    """enqueue all is complete and idempotent.

    Args:
        news_repository: NewsRepository: .

    Returns:
        None: .
    """
    queue = NewsTargetQueue(news_repository)
    run_id = queue.create_run(
        scope_version_id="scope-1",
        quant_run_id="quant-1",
        decision_at=datetime(2026, 6, 22, tzinfo=UTC),
    )
    replay_run_id = queue.create_run(
        scope_version_id="scope-1",
        quant_run_id="quant-1",
        decision_at=datetime(2026, 6, 22, tzinfo=UTC),
    )

    queue.enqueue_all(run_id, [make_target("000001"), make_target("000002")])
    queue.enqueue_all(run_id, [make_target("000001"), make_target("000002")])

    reconciliation = queue.reconcile(run_id)
    assert replay_run_id == run_id
    assert reconciliation.target_count == 2
    assert reconciliation.pending_count == 2


def test_claim_batch_orders_by_priority_and_retry_time(
    news_repository: NewsRepository,
) -> None:
    """claim batch orders by priority and retry time.

    Args:
        news_repository: NewsRepository: .

    Returns:
        None: .
    """
    queue = NewsTargetQueue(news_repository)
    run_id = queue.create_run(
        scope_version_id="scope-1",
        quant_run_id="quant-1",
        decision_at=datetime(2026, 6, 22, tzinfo=UTC),
    )
    queue.enqueue_all(run_id, [make_target("000001", 5), make_target("000002", 99)])

    batch = queue.claim_batch(
        run_id,
        limit=1,
        now=datetime(2026, 6, 22, tzinfo=UTC),
    )

    assert [item.target.symbol for item in batch] == ["000002"]
    assert batch[0].target.status == NewsTargetStatus.CLAIMED


def test_failed_retry_does_not_make_run_terminal(
    news_repository: NewsRepository,
) -> None:
    """failed retry does not make run terminal.

    Args:
        news_repository: NewsRepository: .

    Returns:
        None: .
    """
    queue = NewsTargetQueue(news_repository)
    run_id = queue.create_run(
        scope_version_id="scope-1",
        quant_run_id="quant-1",
        decision_at=datetime(2026, 6, 22, tzinfo=UTC),
    )
    queue.enqueue_all(run_id, [make_target("000001")])
    [item] = queue.claim_batch(
        run_id,
        limit=1,
        now=datetime(2026, 6, 22, tzinfo=UTC),
    )

    queue.mark_retry(
        item.target_id,
        error_code="provider_429",
        error_message="rate limited",
        next_attempt_at=datetime(2026, 6, 22, tzinfo=UTC) + timedelta(minutes=5),
    )

    assert queue.reconcile(run_id) == TargetReconciliation(
        target_count=1,
        pending_count=0,
        claimed_count=0,
        retry_count=1,
        completed_count=0,
        failed_final_count=0,
        is_terminal=False,
    )
