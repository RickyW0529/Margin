"""Tests for the document-event to persistent-index worker."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from margin.news.models import SourceLevel, make_document_event
from margin.vector.indexing_runner import DocumentIndexingRunner


class FakeNewsRepository:
    def __init__(self, event) -> None:
        self.event = event
        self.delivered: list[int] = []
        self.failed: list[tuple[int, str]] = []

    def claim_outbox(self, topic, limit):
        del topic, limit
        return [SimpleNamespace(outbox_id=1, event_id=self.event.event_id)]

    def get_document_event(self, event_id):
        return self.event if event_id == self.event.event_id else None

    def mark_outbox_delivered(self, outbox_id):
        self.delivered.append(outbox_id)

    def mark_outbox_failed(self, outbox_id, error):
        self.failed.append((outbox_id, error))


class FakeEmbeddingProvider:
    name = "fake_embedding"
    version = "v1"

    def embed_batch(self, texts):
        return [[float(len(text)), 1.0] for text in texts]


class FakeVectorRepository:
    def __init__(self) -> None:
        self.chunks = []
        self.embeddings = []
        self.audits = []

    def upsert_chunks(self, chunks):
        self.chunks.extend(chunks)
        return len(chunks)

    def upsert_embeddings(self, items, **metadata):
        self.embeddings.extend(items)
        self.embedding_metadata = metadata
        return len(items)

    def record_index_audit(self, **audit):
        self.audits.append(audit)
        return 1


def test_indexing_runner_consumes_outbox_and_persists_chunks_and_vectors():
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
