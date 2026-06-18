"""Transactional document event publisher and outbox consumer."""

from __future__ import annotations

from margin.news.models import DocumentEvent
from margin.news.repository import NewsRepository, OutboxMessage


class DocumentEventPublisher:
    """Persist document events and enqueue ready documents atomically."""

    def __init__(self, repository: NewsRepository) -> None:
        self._repository = repository

    def persist_pending(self, event: DocumentEvent) -> None:
        """Persist one event and create an outbox row only when it is indexable."""
        self._repository.add_document_event(event, publishable=True)


class OutboxConsumer:
    """Small consumer facade over the repository outbox methods."""

    def __init__(self, repository: NewsRepository) -> None:
        self._repository = repository

    def claim_batch(self, topic: str, limit: int = 50) -> list[OutboxMessage]:
        """Claim pending messages."""
        return self._repository.claim_outbox(topic, limit)

    def mark_delivered(self, outbox_id: int) -> None:
        """Mark a message delivered."""
        self._repository.mark_outbox_delivered(outbox_id)

    def mark_failed(self, outbox_id: int, error: str) -> None:
        """Mark a message failed."""
        self._repository.mark_outbox_failed(outbox_id, error)
