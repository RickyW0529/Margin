"""Durable target queue for v0.2 target-driven news refresh runs."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import datetime

from margin.news.models import (
    NewsRefreshStatus,
    NewsTarget,
    NewsTargetWorkItem,
    TargetReconciliation,
    utc_now,
)
from margin.news.repository import NewsRepository


class NewsTargetQueue:
    """Persistence-backed queue that owns refresh target completeness semantics.."""

    def __init__(self, repository: NewsRepository) -> None:
        """Initialize the instance.

        Args:
            repository: NewsRepository: .

        Returns:
            None: .
        """
        self._repository = repository

    def create_run(
        self,
        scope_version_id: str,
        quant_run_id: str,
        decision_at: datetime,
    ) -> str:
        """Create a refresh run and return its durable identifier.

        Args:
            scope_version_id: str: .
            quant_run_id: str: .
            decision_at: datetime: .

        Returns:
            str: .
        """
        material = "|".join(
            (
                scope_version_id,
                quant_run_id,
                decision_at.isoformat(),
            )
        )
        run_id = "nr_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
        self._repository.create_news_refresh_run(
            run_id=run_id,
            scope_version_id=scope_version_id,
            quant_run_id=quant_run_id,
            decision_at=decision_at,
        )
        return run_id

    def enqueue_all(self, run_id: str, targets: Sequence[NewsTarget]) -> None:
        """Persist the full target set idempotently before any external call.

        Args:
            run_id: str: .
            targets: Sequence[NewsTarget]: .

        Returns:
            None: .
        """
        target_count = self._repository.upsert_news_targets(run_id, list(targets))
        self._repository.set_news_refresh_target_count(run_id, target_count)

    def claim_batch(
        self,
        run_id: str,
        *,
        limit: int,
        now: datetime | None = None,
    ) -> list[NewsTargetWorkItem]:
        """Claim a batch of eligible targets ordered by priority and retry time.

        Args:
            run_id: str: .
            limit: int: .
            now: datetime | None: .

        Returns:
            list[NewsTargetWorkItem]: .
        """
        return self._repository.claim_news_targets(
            run_id,
            limit=limit,
            now=now or utc_now(),
        )

    def mark_completed(
        self,
        target_id: str,
        event_ids: Sequence[str] = (),
    ) -> None:
        """Mark a target completed with optional linked document events.

        Args:
            target_id: str: .
            event_ids: Sequence[str]: .

        Returns:
            None: .
        """
        self._repository.mark_news_target_completed(target_id, tuple(event_ids))

    def mark_retry(
        self,
        target_id: str,
        *,
        error_code: str,
        error_message: str,
        next_attempt_at: datetime,
    ) -> None:
        """Mark a target retryable with explicit backoff timestamp.

        Args:
            target_id: str: .
            error_code: str: .
            error_message: str: .
            next_attempt_at: datetime: .

        Returns:
            None: .
        """
        self._repository.mark_news_target_retry(
            target_id,
            error_code=error_code,
            error_message=error_message,
            next_attempt_at=next_attempt_at,
        )

    def mark_failed_final(
        self,
        target_id: str,
        *,
        error_code: str,
        error_message: str,
    ) -> None:
        """Mark a target as terminal failed.

        Args:
            target_id: str: .
            error_code: str: .
            error_message: str: .

        Returns:
            None: .
        """
        self._repository.mark_news_target_failed_final(
            target_id,
            error_code=error_code,
            error_message=error_message,
        )

    def reconcile(self, run_id: str) -> TargetReconciliation:
        """Return and persist current target counts for a run.

        Args:
            run_id: str: .

        Returns:
            TargetReconciliation: .
        """
        return self._repository.reconcile_news_refresh_run(run_id)

    def mark_run_status(
        self,
        run_id: str,
        *,
        status: NewsRefreshStatus,
        error_summary: dict[str, object] | None = None,
    ) -> None:
        """Persist provider-level wait/failure status for the run.

        Args:
            run_id: str: .
            status: NewsRefreshStatus: .
            error_summary: dict[str, object] | None: .

        Returns:
            None: .
        """
        self._repository.update_news_refresh_run_status(
            run_id,
            status=status,
            error_summary=error_summary,
        )


__all__ = ["NewsTargetQueue", "NewsTargetWorkItem", "TargetReconciliation"]
