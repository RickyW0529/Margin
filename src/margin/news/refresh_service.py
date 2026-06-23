"""Target-driven news refresh orchestration."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Protocol

from margin.news.materiality import DocumentMaterialityService
from margin.news.models import (
    DocumentSecurityLink,
    NewsRefreshRun,
    NewsRefreshStatus,
    NewsTarget,
    TargetReconciliation,
    utc_now,
)
from margin.news.query_templates import QueryTemplateFactory
from margin.news.repository import NewsRepository
from margin.news.target_queue import NewsTargetQueue


class ProviderRateLimited(RuntimeError):
    """Provider-wide rate limit; target coverage must remain intact."""

    def __init__(
        self,
        provider_name: str,
        *,
        retry_after_seconds: int | None = None,
        message: str | None = None,
    ) -> None:
        """Initialize the instance."""
        self.provider_name = provider_name
        self.retry_after_seconds = retry_after_seconds
        super().__init__(message or f"{provider_name} rate limited")


class WebSearchServiceLike(Protocol):
    """Small protocol used by refresh orchestration."""

    def search_and_acquire(
        self,
        query: str,
        max_results: int = 10,
    ) -> tuple[object, list[object]]:
        """Search, verify originals, persist query audit, and return document events."""


class NewsRefreshService:
    """Orchestrate one complete target-driven WebSearch refresh run."""

    def __init__(
        self,
        *,
        queue: NewsTargetQueue,
        websearch_provider: WebSearchServiceLike,
        query_factory: QueryTemplateFactory | None = None,
        retry_backoff: timedelta = timedelta(minutes=5),
        repository: NewsRepository | None = None,
        materiality_service: DocumentMaterialityService | None = None,
    ) -> None:
        """Initialize the instance."""
        self._queue = queue
        self._websearch = websearch_provider
        self._query_factory = query_factory or QueryTemplateFactory()
        self._retry_backoff = retry_backoff
        self._repository = repository
        self._materiality = materiality_service or DocumentMaterialityService()

    def refresh_for_targets(
        self,
        *,
        scope_version_id: str,
        quant_run_id: str,
        decision_at: datetime,
        targets: Sequence[NewsTarget],
        batch_size: int = 20,
    ) -> NewsRefreshRun:
        """Persist all targets first, then process them in bounded batches."""
        run_id = self._queue.create_run(scope_version_id, quant_run_id, decision_at)
        self._queue.enqueue_all(run_id, list(targets))
        while True:
            batch = self._queue.claim_batch(run_id, limit=batch_size, now=utc_now())
            if not batch:
                break
            for item in batch:
                try:
                    event_ids: list[str] = []
                    for query in self._query_factory.build_queries(item.target):
                        _, events = self._websearch.search_and_acquire(
                            query.query,
                            max_results=query.max_results,
                        )
                        event_ids.extend(
                            str(getattr(event, "event_id"))
                            for event in events
                            if getattr(event, "event_id", None)
                        )
                        self._persist_target_links(item.target, events)
                    self._queue.mark_completed(item.target_id, tuple(event_ids))
                except ProviderRateLimited as exc:
                    self._queue.mark_retry(
                        item.target_id,
                        error_code="provider_429",
                        error_message=str(exc),
                        next_attempt_at=utc_now()
                        + timedelta(
                            seconds=exc.retry_after_seconds or 60
                        ),
                    )
                    self._mark_run_status(
                        run_id,
                        NewsRefreshStatus.WAITING_RATE_LIMIT,
                        {
                            "provider": exc.provider_name,
                            "retry_after_seconds": exc.retry_after_seconds,
                        },
                    )
                    reconciliation = self._queue.reconcile(run_id)
                    return self._run_from_reconciliation(
                        run_id=run_id,
                        scope_version_id=scope_version_id,
                        quant_run_id=quant_run_id,
                        decision_at=decision_at,
                        status=NewsRefreshStatus.WAITING_RATE_LIMIT,
                        reconciliation=reconciliation,
                        error_summary={
                            "provider": exc.provider_name,
                            "retry_after_seconds": exc.retry_after_seconds,
                        },
                    )
                except Exception as exc:  # noqa: BLE001 - target failures are isolated
                    if _is_provider_budget_error(exc):
                        retry_after = utc_now() + timedelta(hours=1)
                        self._queue.mark_retry(
                            item.target_id,
                            error_code=str(getattr(exc, "code", "provider_budget_exceeded")),
                            error_message=str(exc),
                            next_attempt_at=retry_after,
                        )
                        self._mark_run_status(
                            run_id,
                            NewsRefreshStatus.WAITING_BUDGET,
                            {
                                "provider": str(
                                    getattr(exc, "provider_name", "websearch")
                                ),
                                "error_code": str(
                                    getattr(
                                        exc,
                                        "code",
                                        "provider_budget_exceeded",
                                    )
                                ),
                            },
                        )
                        reconciliation = self._queue.reconcile(run_id)
                        return self._run_from_reconciliation(
                            run_id=run_id,
                            scope_version_id=scope_version_id,
                            quant_run_id=quant_run_id,
                            decision_at=decision_at,
                            status=NewsRefreshStatus.WAITING_BUDGET,
                            reconciliation=reconciliation,
                            error_summary={
                                "provider": str(
                                    getattr(exc, "provider_name", "websearch")
                                ),
                                "error_code": str(
                                    getattr(
                                        exc,
                                        "code",
                                        "provider_budget_exceeded",
                                    )
                                ),
                            },
                        )
                    self._queue.mark_retry(
                        item.target_id,
                        error_code=exc.__class__.__name__,
                        error_message=str(exc),
                        next_attempt_at=utc_now() + self._retry_backoff,
                    )
        reconciliation = self._queue.reconcile(run_id)
        if reconciliation.is_terminal:
            status = (
                NewsRefreshStatus.PARTIAL
                if reconciliation.failed_final_count
                else NewsRefreshStatus.COMPLETED
            )
        else:
            status = NewsRefreshStatus.RUNNING
        return self._run_from_reconciliation(
            run_id=run_id,
            scope_version_id=scope_version_id,
            quant_run_id=quant_run_id,
            decision_at=decision_at,
            status=status,
            reconciliation=reconciliation,
        )

    def _mark_run_status(
        self,
        run_id: str,
        status: NewsRefreshStatus,
        error_summary: dict[str, object],
    ) -> None:
        """mark run status."""
        marker = getattr(self._queue, "mark_run_status", None)
        if callable(marker):
            marker(run_id, status=status, error_summary=error_summary)

    @staticmethod
    def _run_from_reconciliation(
        *,
        run_id: str,
        scope_version_id: str,
        quant_run_id: str,
        decision_at: datetime,
        status: NewsRefreshStatus,
        reconciliation: TargetReconciliation,
        error_summary: dict[str, object] | None = None,
    ) -> NewsRefreshRun:
        """run from reconciliation."""
        return NewsRefreshRun(
            run_id=run_id,
            scope_version_id=scope_version_id,
            quant_run_id=quant_run_id,
            decision_at=decision_at,
            status=status,
            target_count=reconciliation.target_count,
            completed_count=reconciliation.completed_count,
            failed_final_count=reconciliation.failed_final_count,
            error_summary=dict(error_summary or {}),
        )

    def _persist_target_links(
        self,
        target: NewsTarget,
        events: list[object],
    ) -> None:
        """Persist deterministic document/security links and materiality."""
        if self._repository is None:
            return
        for event in events:
            event_id = getattr(event, "event_id", None)
            if not event_id:
                continue
            self._repository.add_document_security_link(
                DocumentSecurityLink(
                    event_id=str(event_id),
                    security_id=target.security_id,
                    symbol=target.symbol,
                    relation_type="targeted_search",
                    source="news_refresh",
                )
            )
            self._repository.add_document_materiality_score(
                self._materiality.score(
                    event_id=str(event_id),
                    title=str(getattr(event, "title", "")),
                    content=getattr(event, "content", None),
                    symbols=(target.security_id,),
                    target_symbol=target.security_id,
                    source_level=int(getattr(event, "source_level", 4)),
                )
            )


def _is_provider_budget_error(exc: Exception) -> bool:
    """Return whether a Provider error represents an account budget wait."""
    return str(getattr(exc, "code", "")) in {
        "provider_budget_exceeded",
        "provider_paygo_limit_exceeded",
    }


__all__ = ["NewsRefreshService", "ProviderRateLimited"]
