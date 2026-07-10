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
    """Stub news repository that yields a single outbox entry for testing.."""

    def __init__(self, event) -> None:
        """Initialize the fake repository with a document event.

        Args:
            event: Any: .

        Returns:
            None: .
        """
        self.event = event
        self.delivered: list[int] = []
        self.failed: list[tuple[int, str]] = []

    def claim_outbox(self, topic, limit):
        """Return a single-element outbox list regardless of topic or limit.

        Args:
            topic: Any: .
            limit: Any: .

        Returns:
            Any: .
        """
        del topic, limit
        return [SimpleNamespace(outbox_id=1, event_id=self.event.event_id)]

    def get_document_event(self, event_id):
        """Return the stored event when the ID matches, otherwise ``None``.

        Args:
            event_id: Any: .

        Returns:
            Any: .
        """
        return self.event if event_id == self.event.event_id else None

    def mark_outbox_delivered(self, outbox_id):
        """Record an outbox ID as successfully delivered.

        Args:
            outbox_id: Any: .

        Returns:
            Any: .
        """
        self.delivered.append(outbox_id)

    def mark_outbox_failed(self, outbox_id, error):
        """Record an outbox ID and error message as failed.

        Args:
            outbox_id: Any: .
            error: Any: .

        Returns:
            Any: .
        """
        self.failed.append((outbox_id, error))


class FakeEmbeddingProvider:
    """Stub embedding provider producing deterministic 2-D vectors for testing.."""

    name = "fake_embedding"
    version = "v1"

    def embed_batch(self, texts):
        """Return one 2-D vector per input text based on text length.

        Args:
            texts: Any: .

        Returns:
            Any: .
        """
        return [[float(len(text)), 1.0] for text in texts]


class FakeVectorRepository:
    """Stub vector repository that records chunks, embeddings, and audit calls.."""

    def __init__(self) -> None:
        """Initialize empty storage lists for chunks, embeddings, and audits.

        Returns:
            None: .
        """
        self.chunks = []
        self.embeddings = []
        self.audits = []
        self.links = []

    def upsert_chunks(self, chunks, *, links=None):
        """Store chunks and return the count added.

        Args:
            chunks: Any: .

        Returns:
            Any: .
        """
        self.chunks.extend(chunks)
        self.links.extend(links or [])
        return len(chunks)

    def upsert_embeddings(self, items, **metadata):
        """Store embedding items and metadata, returning the count added.

        Args:
            items: Any: .
            **metadata: Any: .

        Returns:
            Any: .
        """
        self.embeddings.extend(items)
        self.embedding_metadata = metadata
        return len(items)

    def record_index_audit(self, **audit):
        """Record an audit entry and return a synthetic audit ID.

        Args:
            **audit: Any: .

        Returns:
            Any: .
        """
        self.audits.append(audit)
        return 1


def test_indexing_runner_consumes_outbox_and_persists_chunks_and_vectors():
    """Runner must consume outbox entries and persist chunks, embeddings, and audits.

    Returns:
        Any: .
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


def test_indexing_runner_uses_full_markdown_offsets_and_structure() -> None:
    """Canonical Markdown chunks must retain global source spans without dropping text."""
    content = "# 经营情况\n\n" + ("需求持续增长。" * 400)
    event = make_document_event(
        source_url="https://example.com/full-report",
        source_name="exchange",
        source_level=SourceLevel.L1,
        title="经营情况",
        content=content,
        symbols=["000001.SZ", "600000.SH"],
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

    assert indexed == len(vector_repository.chunks)
    assert indexed > 1
    assert len(vector_repository.links) == indexed * 2
    for chunk in vector_repository.chunks:
        assert chunk.quote_span is not None
        start, end = chunk.quote_span
        assert event.content[start:end] == chunk.content
        assert chunk.section == "经营情况"
