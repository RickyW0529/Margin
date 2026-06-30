"""Tests for the document-event to persistent-index worker.

Verifies that ``DocumentIndexingRunner`` consumes outbox entries, chunks document
events, persists chunks and embeddings via the vector repository, records audit
metadata, and marks the outbox entry as delivered.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from margin.news.models import SourceLevel, make_document_event
from margin.vector.indexing_runner import DocumentIndexingRunner


class FakeNewsRepository:
    """Stub news repository that yields a single outbox entry for testing.

    Tracks delivered and failed outbox IDs to verify runner behavior.
    """

    def __init__(self, event) -> None:
        """Initialize the fake repository with a document event.

        Args:
            event: the document event returned by ``get_document_event``.
        """
        self.event = event
        self.delivered: list[int] = []
        self.failed: list[tuple[int, str]] = []

    def claim_outbox(self, topic, limit):
        """Return a single-element outbox list regardless of topic or limit."""
        del topic, limit
        return [SimpleNamespace(outbox_id=1, event_id=self.event.event_id)]

    def get_document_event(self, event_id):
        """Return the stored event when the ID matches, otherwise ``None``."""
        return self.event if event_id == self.event.event_id else None

    def mark_outbox_delivered(self, outbox_id):
        """Record an outbox ID as successfully delivered."""
        self.delivered.append(outbox_id)

    def mark_outbox_failed(self, outbox_id, error):
        """Record an outbox ID and error message as failed."""
        self.failed.append((outbox_id, error))


class FakeEmbeddingProvider:
    """Stub embedding provider producing deterministic 2-D vectors for testing.

    Attributes:
        name: provider name used in audit records.
        version: provider version string.
    """
    name = "fake_embedding"
    version = "v1"

    def embed_batch(self, texts):
        """Return one 2-D vector per input text based on text length."""
        return [[float(len(text)), 1.0] for text in texts]


class FakeVectorRepository:
    """Stub vector repository that records chunks, embeddings, and audit calls."""

    def __init__(self) -> None:
        """Initialize empty storage lists for chunks, embeddings, and audits."""
        self.chunks = []
        self.embeddings = []
        self.audits = []

    def upsert_chunks(self, chunks):
        """Store chunks and return the count added."""
        self.chunks.extend(chunks)
        return len(chunks)

    def upsert_embeddings(self, items, **metadata):
        """Store embedding items and metadata, returning the count added."""
        self.embeddings.extend(items)
        self.embedding_metadata = metadata
        return len(items)

    def record_index_audit(self, **audit):
        """Record an audit entry and return a synthetic audit ID."""
        self.audits.append(audit)
        return 1


def test_indexing_runner_consumes_outbox_and_persists_chunks_and_vectors():
    """Runner must consume outbox entries and persist chunks, embeddings, and audits.

    Verifies that ``DocumentIndexingRunner.run_once`` claims an outbox entry, chunks
    the document event, persists chunks and embeddings via the vector repository,
    records a non-degraded audit entry, and marks the outbox as delivered.
    """
    event = make_document_event(
        source_url="https://example.com/filing",
        source_name="exchange",
        source_level=SourceLevel.L1,
        title="经营公告",
        content="经营现金流改善。",
        symbols=["000001.SZ"],
        doc_type="filing",
        published_at=datetime(2026, 6, 18, tzinfo=UTC),
        available_at=datetime(2026, 6, 18, tzinfo=UTC),
    )
    news_repository = FakeNewsRepository(event)
    vector_repository = FakeVectorRepository()
    runner = DocumentIndexingRunner(
        news_repository=news_repository,
        vector_repository=vector_repository,
        embedding_provider=FakeEmbeddingProvider(),
    )

    indexed = runner.run_once()

    assert indexed > 0
    assert vector_repository.chunks
    assert len(vector_repository.embeddings) == indexed
    assert vector_repository.audits[0]["degraded"] is False
    assert news_repository.delivered == [1]
    assert news_repository.failed == []
