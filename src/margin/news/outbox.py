"""Transactional document event publisher and outbox consumer."""

from __future__ import annotations

from margin.news.models import DocumentEvent
from margin.news.repository import NewsRepository, OutboxMessage


class DocumentEventPublisher:
    """Persist document events and enqueue ready documents atomically."""

    def __init__(self, repository: NewsRepository) -> None:
        """Initialize the publisher.

        Args:
            repository: Repository used to persist events and outbox rows.
        """
        self._repository = repository

    def persist_pending(self, event: DocumentEvent) -> None:
        """Persist one event and create an outbox row only when it is indexable.

        Args:
            event: Document event to persist and enqueue.
        """
        self._repository.add_document_event(event, publishable=True)


class OutboxConsumer:
    """Small consumer facade over the repository outbox methods."""

    def __init__(self, repository: NewsRepository) -> None:
        """Initialize the consumer.

        Args:
            repository: Repository used to claim and update outbox rows.
        """
        self._repository = repository

    def claim_batch(self, topic: str, limit: int = 50) -> list[OutboxMessage]:
        """Claim pending messages.

        Args:
            topic: Destination topic to claim messages for.
            limit: Maximum number of messages to claim.

        Returns:
            List of claimed outbox messages.
        """
        return self._repository.claim_outbox(topic, limit)

    def mark_delivered(self, outbox_id: int) -> None:
        """Mark a message delivered.

        Args:
            outbox_id: Primary key of the outbox row to update.
        """
        self._repository.mark_outbox_delivered(outbox_id)

    def mark_failed(self, outbox_id: int, error: str) -> None:
        """Mark a message failed.

        Args:
            outbox_id: Primary key of the outbox row to update.
            error: Error message to record for audit.
        """
        self._repository.mark_outbox_failed(outbox_id, error)
