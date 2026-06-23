"""Official filing incremental sync wrapper."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from margin.news.discovery import DiscoveredDocument
from margin.news.models import DocumentEvent
from margin.news.repository import NewsRepository


class OfficialDiscoveryLike(Protocol):
    """Protocol for official exchange announcement discovery."""

    def discover(
        self,
        cursor: str | None,
        limit: int,
    ) -> list[DiscoveredDocument]:
        """Discover official documents after the provided cursor."""


class FilingAcquirerLike(Protocol):
    """Protocol for the existing filing acquirer boundary."""

    def acquire(
        self,
        source_name: str,
        url: str,
        **kwargs: object,
    ) -> DocumentEvent:
        """Acquire one official filing and return a normalized event."""


class FilingSyncRun(BaseModel):
    """Summary of one official filing sync pass."""

    source_name: str
    cursor_key: str
    started_cursor: str | None
    finished_cursor: str | None
    discovered_records: int
    persisted_events: int
    duplicate_records: int
    failed_records: int
    status: str

    model_config = {"frozen": True}


class OfficialFilingSyncService:
    """Sync official filings globally and advance cursor only after persistence."""

    def __init__(
        self,
        repository: NewsRepository,
        discovery: OfficialDiscoveryLike,
        acquirer: FilingAcquirerLike,
    ) -> None:
        """Initialize the instance."""
        self._repository = repository
        self._discovery = discovery
        self._acquirer = acquirer

    def sync(
        self,
        *,
        source_name: str,
        cursor_key: str,
        limit: int = 100,
    ) -> FilingSyncRun:
        """Run one incremental sync batch for an official source."""
        started_cursor = self._repository.get_cursor(source_name, cursor_key)
        records = self._discovery.discover(cursor=started_cursor, limit=limit)
        persisted_events = 0
        duplicate_records = 0
        failed_records = 0
        finished_cursor = started_cursor

        for record in records:
            try:
                event = self._acquirer.acquire(
                    source_name,
                    record.source_url,
                    title_override=record.title,
                    published_at=record.published_at,
                    external_id=record.external_id,
                )
                existing = self._repository.get_document_event(event.event_id)
                self._repository.add_document_event(event)
                if existing is None:
                    persisted_events += 1
                else:
                    duplicate_records += 1
                if record.cursor is not None:
                    self._repository.upsert_cursor(
                        source_name,
                        cursor_key,
                        record.cursor,
                    )
                    finished_cursor = record.cursor
            except Exception:  # noqa: BLE001 - one bad filing must not advance cursor
                failed_records += 1

        if failed_records == 0:
            status = "completed"
        elif persisted_events > 0 or duplicate_records > 0:
            status = "partial"
        else:
            status = "failed"

        return FilingSyncRun(
            source_name=source_name,
            cursor_key=cursor_key,
            started_cursor=started_cursor,
            finished_cursor=finished_cursor,
            discovered_records=len(records),
            persisted_events=persisted_events,
            duplicate_records=duplicate_records,
            failed_records=failed_records,
            status=status,
        )


__all__ = ["FilingSyncRun", "OfficialFilingSyncService"]
