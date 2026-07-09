"""Agentic news acquisition orchestration tests."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from threading import Barrier, BrokenBarrierError
from types import SimpleNamespace

import pytest

from margin.news.agentic_acquisition import AgenticNewsAcquisitionService
from margin.news.agentic_models import (
    NewsAgentRunStatus,
    NewsArticleFinding,
    NewsSearchPlan,
    NewsSecurityBrief,
)
from margin.news.models import (
    NewsTarget,
    SourceLevel,
    TargetTriggerType,
    make_document_event,
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
    """Create a clean news repository.

    Args:
        database_url: str: .

    Yields:
        Any: .
    """
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    repo = NewsRepository(session_factory)
    yield repo
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_agentic_acquisition_persists_run_plan_findings_and_brief(
    news_repository: NewsRepository,
) -> None:
    """A normal agentic acquisition run persists all auditable artifacts.

    Args:
        news_repository: NewsRepository: .

    Returns:
        None: .
    """
    target = _target()
    websearch = FakeWebSearch(news_repository)
    service = AgenticNewsAcquisitionService(
        repository=news_repository,
        target_repository=FakeTargetRepository((target,)),
        keyword_workflow=FakeKeywordWorkflow(),
        websearch_service=websearch,
        article_workflow=FakeArticleWorkflow(),
    )

    result = service.run_for_quant_run(
        scope_version_id="scope_v1",
        quant_run_id="qr_test",
        decision_at=target.decision_at,
        include_near_threshold=False,
    )

    assert result.status == NewsAgentRunStatus.COMPLETED
    stored_run = news_repository.get_news_agent_run(result.run_id)
    assert stored_run is not None
    assert stored_run.target_count == 1
    assert news_repository.list_news_search_plans(result.run_id)
    assert news_repository.list_news_article_findings(result.run_id, "000001.SZ")
    assert news_repository.list_news_security_briefs(result.run_id)
    assert websearch.calls == ["平安银行 000001.SZ 公告"]
    assert news_repository.get_outbox_by_event("evt_agentic", "vector_index") is not None


def test_agentic_acquisition_empty_pass_set_completes_without_provider_calls(
    news_repository: NewsRepository,
) -> None:
    """An empty PASS target set completes without WebSearch or LLM work.

    Args:
        news_repository: NewsRepository: .

    Returns:
        None: .
    """
    websearch = FakeWebSearch(news_repository)
    service = AgenticNewsAcquisitionService(
        repository=news_repository,
        target_repository=FakeTargetRepository(()),
        keyword_workflow=FakeKeywordWorkflow(),
        websearch_service=websearch,
        article_workflow=FakeArticleWorkflow(),
    )

    result = service.run_for_quant_run(
        scope_version_id="scope_v1",
        quant_run_id="qr_empty",
        decision_at=datetime(2026, 6, 29, tzinfo=UTC),
    )

    assert result.status == NewsAgentRunStatus.COMPLETED_EMPTY
    assert result.target_count == 0
    assert websearch.calls == []
    assert news_repository.list_news_search_plans(result.run_id) == []


def test_agentic_acquisition_waits_when_websearch_budget_is_exceeded(
    news_repository: NewsRepository,
) -> None:
    """Provider budget errors pause the run instead of becoming generic partials.

    Args:
        news_repository: NewsRepository: .

    Returns:
        None: .
    """
    target = _target()
    service = AgenticNewsAcquisitionService(
        repository=news_repository,
        target_repository=FakeTargetRepository((target,)),
        keyword_workflow=FakeKeywordWorkflow(),
        websearch_service=BudgetExceededWebSearch(),
        article_workflow=FakeArticleWorkflow(),
    )

    result = service.run_for_quant_run(
        scope_version_id="scope_v1",
        quant_run_id="qr_budget",
        decision_at=target.decision_at,
        include_near_threshold=False,
    )

    assert result.status == NewsAgentRunStatus.WAITING_PROVIDER
    assert result.error_summary["error_code"] == "provider_budget_exceeded"
    assert result.error_summary["provider"] == "tavily_websearch"
    assert news_repository.list_news_search_plans(result.run_id)


def test_agentic_acquisition_is_idempotent_for_same_key(
    news_repository: NewsRepository,
) -> None:
    """Repeating the same idempotency key should return the existing run.

    Args:
        news_repository: NewsRepository: .

    Returns:
        None: .
    """
    target = _target()
    websearch = FakeWebSearch(news_repository)
    service = AgenticNewsAcquisitionService(
        repository=news_repository,
        target_repository=FakeTargetRepository((target,)),
        keyword_workflow=FakeKeywordWorkflow(),
        websearch_service=websearch,
        article_workflow=FakeArticleWorkflow(),
    )

    first = service.run_for_quant_run(
        scope_version_id="scope_v1",
        quant_run_id="qr_test",
        decision_at=target.decision_at,
        idempotency_key="same-request",
    )
    second = service.run_for_quant_run(
        scope_version_id="scope_v1",
        quant_run_id="qr_test",
        decision_at=target.decision_at,
        idempotency_key="same-request",
    )

    assert second.run_id == first.run_id
    assert websearch.calls == ["平安银行 000001.SZ 公告"]


def test_agentic_acquisition_uses_max_workers_for_targets(
    news_repository: NewsRepository,
) -> None:
    """Multiple targets should be processed concurrently when max_workers allows it.

    Args:
        news_repository: NewsRepository: .

    Returns:
        None: .
    """
    targets = (
        _target(security_id="000001.SZ", name="平安银行"),
        _target(security_id="000002.SZ", name="万科A"),
    )
    websearch = BarrierWebSearch(parties=2)
    service = AgenticNewsAcquisitionService(
        repository=news_repository,
        target_repository=FakeTargetRepository(targets),
        keyword_workflow=TargetKeywordWorkflow(),
        websearch_service=websearch,
        article_workflow=EmptyArticleWorkflow(),
    )

    result = service.run_for_quant_run(
        scope_version_id="scope_v1",
        quant_run_id="qr_parallel",
        decision_at=targets[0].decision_at,
        max_workers=2,
    )

    assert result.status == NewsAgentRunStatus.COMPLETED
    assert sorted(websearch.calls) == [
        "万科A 000002.SZ 公告",
        "平安银行 000001.SZ 公告",
    ]


def test_agentic_acquisition_persists_failed_target_task(
    news_repository: NewsRepository,
) -> None:
    """Target failures should include security-level task audit details.

    Args:
        news_repository: NewsRepository: .

    Returns:
        None: .
    """
    targets = (
        _target(security_id="000001.SZ", name="平安银行"),
        _target(security_id="000002.SZ", name="万科A"),
    )
    service = AgenticNewsAcquisitionService(
        repository=news_repository,
        target_repository=FakeTargetRepository(targets),
        keyword_workflow=TargetKeywordWorkflow(),
        websearch_service=FailingWebSearch(fail_query="万科A 000002.SZ 公告"),
        article_workflow=EmptyArticleWorkflow(),
    )

    result = service.run_for_quant_run(
        scope_version_id="scope_v1",
        quant_run_id="qr_fail",
        decision_at=targets[0].decision_at,
    )

    tasks = news_repository.list_news_agent_tasks(result.run_id)
    failed = [task for task in tasks if task.status.value == "failed_final"]

    assert result.status == NewsAgentRunStatus.PARTIAL
    assert len(failed) == 1
    assert failed[0].security_id == "000002.SZ"
    assert failed[0].task_type == "target_pipeline"
    assert failed[0].error_code == "RuntimeError"


class FakeTargetRepository:
    """Fake quant target repository.."""

    def __init__(self, targets: tuple[NewsTarget, ...]) -> None:
        """Initialize the fake target repository with a fixed target tuple.

        Args:
            targets: tuple[NewsTarget, ...]: .

        Returns:
            None: .
        """
        self._targets = targets

    def list_targets(self, **_: object) -> tuple[NewsTarget, ...]:
        """Return configured targets.

        Args:
            **_: object: .

        Returns:
            tuple[NewsTarget, ...]: .
        """
        return self._targets


class FakeKeywordWorkflow:
    """Fake keyword workflow.."""

    def build_plan(self, *, run_id: str, target: NewsTarget) -> NewsSearchPlan:
        """Return one approved search plan.

        Args:
            run_id: str: .
            target: NewsTarget: .

        Returns:
            NewsSearchPlan: .
        """
        return NewsSearchPlan(
            plan_id=f"nsp_{target.security_id}",
            run_id=run_id,
            security_id=target.security_id,
            symbol=target.symbol,
            name=target.name,
            queries=("平安银行 000001.SZ 公告",),
            review_status="approved",
            fallback_used=False,
        )


class TargetKeywordWorkflow:
    """Keyword workflow that emits one target-specific query.."""

    def build_plan(self, *, run_id: str, target: NewsTarget) -> NewsSearchPlan:
        """Return one query using the target name and symbol.

        Args:
            run_id: str: .
            target: NewsTarget: .

        Returns:
            NewsSearchPlan: .
        """
        return NewsSearchPlan(
            plan_id=f"nsp_{target.security_id}",
            run_id=run_id,
            security_id=target.security_id,
            symbol=target.symbol,
            name=target.name,
            queries=(f"{target.name} {target.symbol} 公告",),
            review_status="approved",
            fallback_used=False,
        )


class FakeWebSearch:
    """Fake WebSearch service that persists a ready document event.."""

    def __init__(self, repository: NewsRepository) -> None:
        """Initialize the fake WebSearch service with a repository.

        Args:
            repository: NewsRepository: .

        Returns:
            None: .
        """
        self._repository = repository
        self.calls: list[str] = []

    def search_and_acquire(
        self,
        query: str,
        max_results: int = 10,
    ) -> tuple[SimpleNamespace, list[object]]:
        """Persist and return one event.

        Args:
            query: str: .
            max_results: int: .

        Returns:
            tuple[SimpleNamespace, list[object]]: .
        """
        self.calls.append(query)
        event = make_document_event(
            source_url="https://example.com/agentic",
            source_name="websearch",
            source_level=SourceLevel.L4,
            title="平安银行公告",
            content="平安银行公告披露经营情况改善。",
            symbols=["000001.SZ"],
            published_at=datetime(2026, 6, 29, tzinfo=UTC),
        ).model_copy(
            update={
                "event_id": "evt_agentic",
                "document_id": "doc_agentic",
            }
        )
        self._repository.add_document_event(event, publishable=True)
        return SimpleNamespace(query_id="sq_agentic"), [event]


class BarrierWebSearch:
    """Fake WebSearch that fails under serial execution and succeeds in parallel.."""

    def __init__(self, parties: int) -> None:
        """Initialize the barrier fake.

        Args:
            parties: int: .

        Returns:
            None: .
        """
        self._barrier = Barrier(parties, timeout=1.0)
        self.calls: list[str] = []

    def search_and_acquire(
        self,
        query: str,
        max_results: int = 10,
    ) -> tuple[SimpleNamespace, list[object]]:
        """Wait for the peer target before returning no events.

        Args:
            query: str: .
            max_results: int: .

        Returns:
            tuple[SimpleNamespace, list[object]]: .
        """
        del max_results
        self.calls.append(query)
        try:
            self._barrier.wait()
        except BrokenBarrierError as exc:
            raise RuntimeError("target was not processed concurrently") from exc
        return SimpleNamespace(query_id=f"sq_{len(self.calls)}"), []


class FailingWebSearch:
    """Fake WebSearch that fails for one query.."""

    def __init__(self, *, fail_query: str) -> None:
        """Initialize with the query that should fail.

        Args:
            fail_query: str: .

        Returns:
            None: .
        """
        self._fail_query = fail_query

    def search_and_acquire(
        self,
        query: str,
        max_results: int = 10,
    ) -> tuple[SimpleNamespace, list[object]]:
        """Raise for one query and return no events for others.

        Args:
            query: str: .
            max_results: int: .

        Returns:
            tuple[SimpleNamespace, list[object]]: .
        """
        del max_results
        if query == self._fail_query:
            raise RuntimeError("download failed")
        return SimpleNamespace(query_id="sq_ok"), []


class BudgetExceededWebSearch:
    """Fake WebSearch service that raises a stable provider budget error.."""

    def search_and_acquire(
        self,
        query: str,
        max_results: int = 10,
    ) -> tuple[SimpleNamespace, list[object]]:
        """Raise a provider budget error.

        Args:
            query: str: .
            max_results: int: .

        Returns:
            tuple[SimpleNamespace, list[object]]: .
        """
        del query, max_results
        raise ProviderBudgetExceeded()


class ProviderBudgetExceeded(RuntimeError):
    """Stable fake Tavily budget exception.."""

    provider_name = "tavily_websearch"
    code = "provider_budget_exceeded"
    retryable = False


class FakeArticleWorkflow:
    """Fake article workflow.."""

    def extract_findings(
        self,
        *,
        run_id: str,
        target: NewsTarget,
        events: tuple[object, ...],
    ) -> tuple[NewsArticleFinding, ...]:
        """Return one approved finding for returned events.

        Args:
            run_id: str: .
            target: NewsTarget: .
            events: tuple[object, ...]: .

        Returns:
            tuple[NewsArticleFinding, ...]: .
        """
        return (
            NewsArticleFinding(
                finding_id="naf_agentic",
                run_id=run_id,
                security_id=target.security_id,
                event_id=str(getattr(events[0], "event_id")),
                title="平安银行公告",
                source_url="https://example.com/agentic",
                key_points=("经营情况改善。",),
                cited_spans=({"start": 0, "end": 8},),
                review_status="approved",
                confidence=0.8,
            ),
        )

    def build_brief(
        self,
        *,
        run_id: str,
        target: NewsTarget,
        findings: tuple[NewsArticleFinding, ...],
    ) -> NewsSecurityBrief:
        """Return one derived brief.

        Args:
            run_id: str: .
            target: NewsTarget: .
            findings: tuple[NewsArticleFinding, ...]: .

        Returns:
            NewsSecurityBrief: .
        """
        return NewsSecurityBrief(
            brief_id="nsb_agentic",
            run_id=run_id,
            security_id=target.security_id,
            summary="平安银行出现一条经营改善公告。",
            finding_ids=tuple(finding.finding_id for finding in findings),
            source_event_ids=tuple(finding.event_id for finding in findings),
        )


class EmptyArticleWorkflow:
    """Article workflow that returns no findings.."""

    def extract_findings(
        self,
        *,
        run_id: str,
        target: NewsTarget,
        events: tuple[object, ...],
    ) -> tuple[NewsArticleFinding, ...]:
        """Return no findings.

        Args:
            run_id: str: .
            target: NewsTarget: .
            events: tuple[object, ...]: .

        Returns:
            tuple[NewsArticleFinding, ...]: .
        """
        del run_id, target, events
        return ()

    def build_brief(
        self,
        *,
        run_id: str,
        target: NewsTarget,
        findings: tuple[NewsArticleFinding, ...],
    ) -> None:
        """Return no brief.

        Args:
            run_id: str: .
            target: NewsTarget: .
            findings: tuple[NewsArticleFinding, ...]: .

        Returns:
            None: .
        """
        del run_id, target, findings
        return None


def _target(
    *,
    security_id: str = "000001.SZ",
    name: str = "平安银行",
) -> NewsTarget:
    """Return one PASS target.

    Args:
        security_id: str: .
        name: str: .

    Returns:
        NewsTarget: .
    """
    return NewsTarget(
        scope_version_id="scope_v1",
        quant_run_id="qr_test",
        security_id=security_id,
        symbol=security_id,
        name=name,
        trigger_type=TargetTriggerType.QUANT_PASS,
        decision_at=datetime(2026, 6, 29, tzinfo=UTC),
        priority=100,
    )
