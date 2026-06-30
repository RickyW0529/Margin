"""Repository tests for agentic news acquisition artifacts."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from margin.news.agentic_models import (
    NewsAgentRun,
    NewsAgentRunStatus,
    NewsArticleFinding,
    NewsSearchPlan,
    NewsSecurityBrief,
)
from margin.news.repository import NewsRepository
from margin.storage.base import Base
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)


@pytest.fixture
def news_repository(database_url: str) -> Iterator[NewsRepository]:
    """Create a clean news repository for agentic artifact tests."""
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    repo = NewsRepository(session_factory)
    yield repo
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_agentic_run_plan_finding_and_brief_roundtrip(
    news_repository: NewsRepository,
) -> None:
    """Agentic run artifacts round-trip through the news repository."""
    run = NewsAgentRun(
        run_id="nar_test",
        scope_version_id="scope_v1",
        quant_run_id="qr_test",
        decision_at=datetime(2026, 6, 29, tzinfo=UTC),
        status=NewsAgentRunStatus.RUNNING,
        target_count=1,
        include_near_threshold=False,
        config_hash="sha256:test",
    )

    news_repository.add_news_agent_run(run)
    news_repository.add_news_search_plan(
        NewsSearchPlan(
            plan_id="nsp_test",
            run_id=run.run_id,
            security_id="000001.SZ",
            symbol="000001.SZ",
            name="平安银行",
            queries=("平安银行 000001.SZ 公告 业绩",),
            review_status="approved",
            fallback_used=False,
            prompt_version="news-keyword-v0.3.0",
            prompt_hash="sha256:prompt",
            response_hash="sha256:response",
        )
    )
    news_repository.add_news_article_finding(
        NewsArticleFinding(
            finding_id="naf_test",
            run_id=run.run_id,
            security_id="000001.SZ",
            event_id="evt_test",
            title="平安银行公告",
            source_url="https://example.com/a",
            key_points=("公告披露经营情况。",),
            risk_flags=(),
            cited_spans=({"start": 0, "end": 8},),
            review_status="approved",
            confidence=0.8,
            prompt_version="news-article-v0.3.0",
            prompt_hash="sha256:prompt",
            response_hash="sha256:response",
        )
    )
    news_repository.add_news_security_brief(
        NewsSecurityBrief(
            brief_id="nsb_test",
            run_id=run.run_id,
            security_id="000001.SZ",
            summary="平安银行有一条已验证公告。",
            finding_ids=("naf_test",),
            source_event_ids=("evt_test",),
            is_derived=True,
            trust_level="derived_low_trust",
            prompt_version="news-brief-v0.3.0",
            prompt_hash="sha256:prompt",
            response_hash="sha256:response",
        )
    )

    stored_run = news_repository.get_news_agent_run("nar_test")
    assert stored_run is not None
    assert stored_run.target_count == 1
    assert news_repository.list_news_search_plans("nar_test")[0].queries == (
        "平安银行 000001.SZ 公告 业绩",
    )
    assert (
        news_repository.list_news_article_findings("nar_test", "000001.SZ")[0].event_id
        == "evt_test"
    )
    assert news_repository.list_news_security_briefs("nar_test")[0].source_event_ids == (
        "evt_test",
    )
