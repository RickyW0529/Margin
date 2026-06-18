"""Incremental acquisition runner and scheduler helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from margin.news.discovery import DiscoveryConnector
from margin.news.outbox import DocumentEventPublisher
from margin.news.repository import NewsRepository


@dataclass(frozen=True)
class AcquisitionRunResult:
    """Summary of one incremental acquisition run."""

    discovered: int
    published: int
    failed: int


class IncrementalAcquisitionRunner:
    """Run discovery, acquisition, publishing, and cursor advancement."""

    def __init__(
        self,
        *,
        repository: NewsRepository,
        acquirer: Any,
        publisher: DocumentEventPublisher,
        cursor_key: str = "announcements",
    ) -> None:
        self._repository = repository
        self._acquirer = acquirer
        self._publisher = publisher
        self._cursor_key = cursor_key

    def run_once(
        self,
        source_name: str,
        connector: DiscoveryConnector,
        *,
        limit: int = 100,
    ) -> AcquisitionRunResult:
        """Run one restart-safe incremental acquisition pass."""
        cursor = self._repository.get_cursor(source_name, self._cursor_key)
        discovered = connector.discover(cursor=cursor, limit=limit)
        published = 0
        failed = 0
        for document in discovered:
            try:
                event = self._acquirer.acquire(
                    source_name,
                    document.source_url,
                    title_override=document.title,
                    published_at=document.published_at,
                )
                self._publisher.persist_pending(event)
                published += 1
                if document.cursor is not None:
                    self._repository.upsert_cursor(
                        source_name,
                        self._cursor_key,
                        document.cursor,
                    )
            except Exception:
                failed += 1
        return AcquisitionRunResult(
            discovered=len(discovered),
            published=published,
            failed=failed,
        )
