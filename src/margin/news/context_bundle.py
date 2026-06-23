"""Build downstream news context bundles with target-completion semantics."""

from __future__ import annotations

import hashlib

from margin.news.models import (
    NewsContextBundle,
    NewsTargetStatus,
    utc_now,
)
from margin.news.repository import NewsRepository


class NewsContextBundleBuilder:
    """Select ranked documents and encode whether news refresh is complete."""

    def __init__(self, repository: NewsRepository) -> None:
        """Initialize the instance."""
        self._repository = repository

    def build_for_run(
        self,
        *,
        run_id: str,
        security_id: str,
        max_documents: int = 20,
    ) -> NewsContextBundle:
        """Build and persist one security-specific news context bundle."""
        statuses = self._repository.list_target_statuses_for_security(
            run_id=run_id,
            security_id=security_id,
        )
        target_completion_state, can_carry, reasons = self._completion_state(statuses)
        documents = self._repository.list_news_context_documents(
            security_id=security_id,
            max_documents=max_documents,
        )
        bundle_material = f"{run_id}|{security_id}"
        bundle = NewsContextBundle(
            bundle_id=(
                "ncb_"
                + hashlib.sha256(bundle_material.encode("utf-8")).hexdigest()[:24]
            ),
            run_id=run_id,
            security_id=security_id,
            target_completion_state=target_completion_state,
            can_support_verified_carry_forward=can_carry,
            incomplete_reason_codes=tuple(reasons),
            documents=tuple(documents),
            created_at=utc_now(),
        )
        self._repository.add_news_context_bundle(bundle)
        return bundle

    @staticmethod
    def _completion_state(
        statuses: list[NewsTargetStatus],
    ) -> tuple[str, bool, list[str]]:
        """completion state."""
        if not statuses:
            return "failed", False, ["target_missing"]
        if any(status == NewsTargetStatus.RETRY for status in statuses):
            return "partial", False, ["target_retry_pending"]
        if any(
            status in {NewsTargetStatus.PENDING, NewsTargetStatus.CLAIMED}
            for status in statuses
        ):
            return "partial", False, ["target_incomplete"]
        if any(status == NewsTargetStatus.FAILED_FINAL for status in statuses):
            return "failed", False, ["target_failed_final"]
        return "complete", True, []


__all__ = ["NewsContextBundleBuilder"]
