"""v0.2 embedding atomicity and indexed-document audit tests."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import text

from margin.storage.base import Base
from margin.storage.database import DatabaseSettings, create_database_engine, create_session_factory
from margin.vector.db_models import ChunkEmbeddingRow, ChunkRow, IndexedDocumentRow
from margin.vector.models import IndexedDocument, make_chunk
from margin.vector.persistent_pipeline import PersistentIndexingPipeline
from margin.vector.repository import VectorRepository


@pytest.fixture
def vector_repository(database_url: str) -> Iterator[VectorRepository]:
    """vector repository."""
    engine = create_database_engine(DatabaseSettings(url=database_url))
    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    with session_factory.begin() as session:
        for row in (IndexedDocumentRow, ChunkEmbeddingRow, ChunkRow):
            session.query(row).delete()
    yield VectorRepository(session_factory, dimension=2)
    Base.metadata.drop_all(engine)
    engine.dispose()


class FakeEmbeddingProvider:
    """FakeEmbeddingProvider."""
    name = "fake"
    version = "v1"

    def __init__(self, vectors: list[list[float]]) -> None:
        """Initialize the instance."""
        self.vectors = vectors

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """embed batch."""
        return self.vectors[: len(texts)]


def chunk(chunk_id: str):
    """chunk."""
    return make_chunk(document_id="doc-1", content=f"{chunk_id} content").model_copy(
        update={"chunk_id": chunk_id}
    )


def test_embedding_dimension_mismatch_writes_no_vectors(
    vector_repository: VectorRepository,
) -> None:
    """embedding dimension mismatch writes no vectors."""
    provider = FakeEmbeddingProvider(vectors=[[0.1, 0.2], [0.3, 0.4, 0.5]])
    pipeline = PersistentIndexingPipeline(
        repository=vector_repository,
        embedding_provider=provider,
        embedding_dimension=2,
        batch_size=2,
    )
    chunks = [chunk("chk-1"), chunk("chk-2")]
    vector_repository.upsert_chunks(chunks)

    with pytest.raises(ValueError, match="Embedding dimension mismatch"):
        pipeline.embed_and_persist(chunks)

    assert vector_repository.count_embeddings() == 0


def test_indexed_document_audit_tracks_chunk_and_embedding_keys(
    vector_repository: VectorRepository,
) -> None:
    """indexed document audit tracks chunk and embedding keys."""
    provider = FakeEmbeddingProvider(vectors=[[0.1, 0.2]])
    pipeline = PersistentIndexingPipeline(
        repository=vector_repository,
        embedding_provider=provider,
        embedding_dimension=2,
        batch_size=1,
    )
    chunks = [chunk("chk-1")]
    vector_repository.upsert_chunks(chunks)

    document = IndexedDocument(
        document_id="doc-1",
        event_id="event-1",
        parser_version="parser-v0.2.0",
        chunk_ids=("chk-1",),
        embedding_keys=(),
        input_hash="sha256:abc",
    )
    vector_repository.upsert_indexed_document(document)
    keys = pipeline.embed_and_persist(chunks)
    vector_repository.upsert_indexed_document(
        document.model_copy(update={"embedding_keys": tuple(keys)})
    )

    stored = vector_repository.get_indexed_document("doc-1")
    assert stored is not None
    assert stored.chunk_ids == ("chk-1",)
    assert stored.embedding_keys == tuple(keys)
