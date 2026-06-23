"""v0.2 target-driven WebSearch refresh service tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from margin.news.models import (
    NewsRefreshStatus,
    NewsTarget,
    NewsTargetStatus,
    NewsTargetWorkItem,
    TargetReconciliation,
    TargetTriggerType,
)
from margin.news.refresh_service import NewsRefreshService, ProviderRateLimited
from margin.news.websearch import SearchQueryRecord


def target(symbol: str, name: str = "平安银行") -> NewsTarget:
    """Build a refresh target fixture."""
    return NewsTarget(
        scope_version_id="scope-1",
        quant_run_id="quant-1",
        security_id=f"{symbol}.SZ",
        symbol=symbol,
        name=name,
        trigger_type=TargetTriggerType.NEW_PASS,
        decision_at=datetime(2026, 6, 22, tzinfo=UTC),
        priority=40,
    )


class FakeQueue:
    """In-memory queue fake used to assert service ordering semantics."""

    def __init__(self) -> None:
        """Initialize the instance."""
        self.run_id = "run-1"
        self.targets: list[NewsTarget] = []
        self.enqueued_symbols: list[str] = []
        self.completed: list[str] = []
        self.retried: list[str] = []

    def create_run(
        self,
        scope_version_id: str,
        quant_run_id: str,
        decision_at: datetime,
    ) -> str:
        """create run."""
        return self.run_id

    def enqueue_all(self, run_id: str, targets: list[NewsTarget]) -> None:
        """enqueue all."""
        self.targets = list(targets)
        self.enqueued_symbols = [item.symbol for item in targets]

    def claim_batch(
        self,
        run_id: str,
        *,
        limit: int,
        now: datetime | None = None,
    ) -> list[NewsTargetWorkItem]:
        """claim batch."""
        claimed = []
        for index, item in enumerate(self.targets[:limit], start=1):
            claimed.append(
                NewsTargetWorkItem(
                    target_id=f"target-{index}",
                    run_id=run_id,
                    target=item.model_copy(update={"status": NewsTargetStatus.CLAIMED}),
                    claimed_at=now or item.decision_at,
                )
            )
        self.targets = self.targets[limit:]
        return claimed

    def mark_completed(self, target_id: str, event_ids: tuple[str, ...] = ()) -> None:
        """mark completed."""
        self.completed.append(target_id)

    def mark_retry(self, *args: Any, **kwargs: Any) -> None:
        """mark retry."""
        target_id = str(args[0]) if args else str(kwargs["target_id"])
        self.retried.append(target_id)

    def reconcile(self, run_id: str) -> TargetReconciliation:
        """reconcile."""
        return TargetReconciliation(
            target_count=len(self.enqueued_symbols),
            pending_count=0,
            claimed_count=0,
            retry_count=0,
            completed_count=len(self.completed),
            failed_final_count=0,
            is_terminal=len(self.completed) == len(self.enqueued_symbols),
        )


class FakeWebSearchProvider:
    """Minimal WebSearchService-compatible fake."""

    def __init__(self, error: Exception | None = None) -> None:
        """Initialize the instance."""
        self.error = error
        self.queries_seen: list[str] = []

    def search_and_acquire(
        self,
        query: str,
        max_results: int = 10,
    ) -> tuple[SearchQueryRecord, list[Any]]:
        """search and acquire."""
        self.queries_seen.append(query)
        if self.error is not None:
            raise self.error
        return (
            SearchQueryRecord(
                query_id=f"sq-{len(self.queries_seen)}",
                query=query,
                api_provider="fake",
                result_count=0,
            ),
            [],
        )


def test_refresh_persists_all_targets_before_search() -> None:
    """refresh persists all targets before search."""
    fake_queue = FakeQueue()
    fake_websearch = FakeWebSearchProvider()
    service = NewsRefreshService(queue=fake_queue, websearch_provider=fake_websearch)

    run = service.refresh_for_targets(
        scope_version_id="scope-1",
        quant_run_id="quant-1",
        decision_at=datetime(2026, 6, 22, tzinfo=UTC),
        targets=[target("000001"), target("000002"), target("000003")],
        batch_size=1,
    )

    assert fake_queue.enqueued_symbols == ["000001", "000002", "000003"]
    assert fake_websearch.queries_seen[0].startswith("平安银行")
    assert run.target_count == 3
    assert run.status == NewsRefreshStatus.COMPLETED


def test_rate_limit_sets_waiting_rate_limit_without_dropping_targets() -> None:
    """rate limit sets waiting rate limit without dropping targets."""
    fake_queue = FakeQueue()
    provider = FakeWebSearchProvider(
        error=ProviderRateLimited("tavily", retry_after_seconds=60)
    )
    service = NewsRefreshService(queue=fake_queue, websearch_provider=provider)

    run = service.refresh_for_targets(
        scope_version_id="scope-1",
        quant_run_id="quant-1",
        decision_at=datetime(2026, 6, 22, tzinfo=UTC),
        targets=[target("000001"), target("000002")],
        batch_size=10,
    )

    assert run.status == NewsRefreshStatus.WAITING_RATE_LIMIT
    assert fake_queue.reconcile(run.run_id).target_count == 2
    assert fake_queue.retried == ["target-1"]


class ProviderBudgetError(RuntimeError):
    """Budget-exhaustion provider double."""

    code = "provider_budget_exceeded"
    provider_name = "tavily"


def test_budget_limit_sets_waiting_budget_without_dropping_targets() -> None:
    """Account budget exhaustion is durable and does not consume target coverage."""
    fake_queue = FakeQueue()
    provider = FakeWebSearchProvider(error=ProviderBudgetError("budget"))
    service = NewsRefreshService(queue=fake_queue, websearch_provider=provider)

    run = service.refresh_for_targets(
        scope_version_id="scope-1",
        quant_run_id="quant-1",
        decision_at=datetime(2026, 6, 22, tzinfo=UTC),
        targets=[target("000001"), target("000002")],
        batch_size=10,
    )

    assert run.status == NewsRefreshStatus.WAITING_BUDGET
    assert run.error_summary["error_code"] == "provider_budget_exceeded"
    assert fake_queue.retried == ["target-1"]
