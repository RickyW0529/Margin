"""News context bundle tests for downstream RAG/AI semantics."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest

from margin.news.context_bundle import NewsContextBundleBuilder
from margin.news.db_models import (
    DocumentEventRow,
    DocumentMaterialityScoreRow,
    DocumentOutboxRow,
    DocumentSecurityLinkRow,
    NewsContextBundleRow,
    NewsContextDocumentRow,
    NewsRefreshRunRow,
    NewsRefreshTargetRow,
)
from margin.news.materiality import DocumentMaterialityService
from margin.news.models import (
    DocumentSecurityLink,
    NewsTarget,
    SourceLevel,
    TargetTriggerType,
    make_document_event,
)
from margin.news.repository import NewsRepository
from margin.news.target_queue import NewsTargetQueue
from margin.storage.base import Base
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)


@pytest.fixture
def news_repository(database_url: str) -> Iterator[NewsRepository]:
    """Create a seeded repository for context bundle tests.

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
            DocumentOutboxRow,
            DocumentEventRow,
        ):
            session.query(row).delete()
    repo = NewsRepository(session_factory)
    _seed_context_fixture(repo, "run-1", complete=False)
    _seed_context_fixture(repo, "run-complete", complete=True)
    yield repo
    Base.metadata.drop_all(engine)
    engine.dispose()


def _target() -> NewsTarget:
    """Return a deterministic news target fixture for context bundle tests.

    Returns:
        NewsTarget: .
    """
    return NewsTarget(
        scope_version_id="scope-1",
        quant_run_id="quant-1",
        security_id="000001.SZ",
        symbol="000001",
        name="平安银行",
        trigger_type=TargetTriggerType.NEW_PASS,
        decision_at=datetime(2026, 6, 22, tzinfo=UTC),
        priority=40,
    )


def _seed_context_fixture(
    repo: NewsRepository,
    run_id: str,
    *,
    complete: bool,
) -> None:
    """Seed a refresh run, target, document event, and materiality score.

    Args:
        repo: NewsRepository: .
        run_id: str: .
        complete: bool: .

    Returns:
        None: .
    """
    repo.create_news_refresh_run(
        run_id=run_id,
        scope_version_id="scope-1",
        quant_run_id="quant-1",
        decision_at=datetime(2026, 6, 22, tzinfo=UTC),
    )
    queue = NewsTargetQueue(repo)
    queue.enqueue_all(run_id, [_target()])
    [item] = queue.claim_batch(run_id, limit=1, now=datetime(2026, 6, 22, tzinfo=UTC))
    if complete:
        queue.mark_completed(item.target_id, event_ids=("evt_context",))
    else:
        queue.mark_retry(
            item.target_id,
            error_code="provider_429",
            error_message="rate limited",
            next_attempt_at=datetime(2026, 6, 22, tzinfo=UTC) + timedelta(minutes=5),
        )
    queue.reconcile(run_id)

    if repo.get_document_event("evt_context") is None:
        event = make_document_event(
            source_url="https://example.com/context",
            source_name="sse",
            source_level=SourceLevel.L1,
            title="关于平安银行收到监管处罚的公告",
            content="监管机构对公司处以罚款并要求整改。",
            symbols=["000001.SZ"],
            published_at=datetime(2026, 6, 22, tzinfo=UTC),
        ).model_copy(update={"event_id": "evt_context", "document_id": "doc_context"})
        repo.add_document_event(event, publishable=False)
        repo.add_document_security_link(
            DocumentSecurityLink(
                event_id=event.event_id,
                security_id="000001.SZ",
                symbol="000001",
            )
        )
        score = DocumentMaterialityService().score(
            event_id=event.event_id,
            title=event.title,
            content=event.content,
            symbols=event.symbols,
            target_symbol="000001.SZ",
            source_level=int(event.source_level),
        )
        repo.add_document_materiality_score(score)


def test_bundle_includes_completed_documents_and_incomplete_target_summary(
    news_repository: NewsRepository,
) -> None:
    """bundle includes completed documents and incomplete target summary.

    Args:
        news_repository: NewsRepository: .

    Returns:
        None: .
    """
    builder = NewsContextBundleBuilder(news_repository)

    bundle = builder.build_for_run(
        run_id="run-1",
        security_id="000001.SZ",
        max_documents=20,
    )

    assert bundle.security_id == "000001.SZ"
    assert bundle.documents[0].event_id == "evt_context"
    assert bundle.target_completion_state in {"complete", "partial", "failed"}
    assert bundle.can_support_verified_carry_forward is False
    assert bundle.incomplete_reason_codes == ("target_retry_pending",)


def test_complete_bundle_can_support_verified_carry_forward(
    news_repository: NewsRepository,
) -> None:
    """complete bundle can support verified carry forward.

    Args:
        news_repository: NewsRepository: .

    Returns:
        None: .
    """
    builder = NewsContextBundleBuilder(news_repository)

    bundle = builder.build_for_run(run_id="run-complete", security_id="000001.SZ")

    assert bundle.target_completion_state == "complete"
    assert bundle.can_support_verified_carry_forward is True
