"""Application service boundary for v0.2 news refresh APIs."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from pydantic import BaseModel

from margin.news.models import NewsRefreshRun, NewsTarget
from margin.news.refresh_service import NewsRefreshService
from margin.news.repository import NewsRepository


class NewsRunStatus(BaseModel):
    """Read model returned by the news refresh status API.."""

    run_id: str
    status: str
    target_count: int
    pending_count: int
    claimed_count: int
    retry_count: int
    completed_count: int
    failed_final_count: int
    error_summary: dict[str, object]

    model_config = {"frozen": True}


class NewsService:
    """Thin application service over refresh orchestration and repository reads.."""

    def __init__(
        self,
        *,
        repository: NewsRepository,
        refresh_service: NewsRefreshService,
    ) -> None:
        """Initialize the instance.

        Args:
            repository: NewsRepository: .
            refresh_service: NewsRefreshService: .

        Returns:
            None: .
        """
        self._repository = repository
        self._refresh_service = refresh_service

    def start_refresh(
        self,
        *,
        scope_version_id: str,
        quant_run_id: str,
        decision_at: datetime,
        targets: Sequence[NewsTarget],
        idempotency_key: str,
    ) -> NewsRefreshRun:
        """Start a refresh synchronously for now; idempotency key is retained for audit.

        Args:
            scope_version_id: str: .
            quant_run_id: str: .
            decision_at: datetime: .
            targets: Sequence[NewsTarget]: .
            idempotency_key: str: .

        Returns:
            NewsRefreshRun: .
        """
        _ = idempotency_key
        return self._refresh_service.refresh_for_targets(
            scope_version_id=scope_version_id,
            quant_run_id=quant_run_id,
            decision_at=decision_at,
            targets=targets,
        )

    def get_run_status(self, run_id: str) -> NewsRunStatus:
        """Return persisted run status and reconciled target counts.

        Args:
            run_id: str: .

        Returns:
            NewsRunStatus: .
        """
        run = self._repository.get_news_refresh_run(run_id)
        if run is None:
            raise KeyError(run_id)
        reconciliation = self._repository.reconcile_news_refresh_run(run_id)
        refreshed = self._repository.get_news_refresh_run(run_id) or run
        return NewsRunStatus(
            run_id=run_id,
            status=refreshed.status.value,
            target_count=reconciliation.target_count,
            pending_count=reconciliation.pending_count,
            claimed_count=reconciliation.claimed_count,
            retry_count=reconciliation.retry_count,
            completed_count=reconciliation.completed_count,
            failed_final_count=reconciliation.failed_final_count,
            error_summary=refreshed.error_summary,
        )


__all__ = ["NewsRunStatus", "NewsService"]
