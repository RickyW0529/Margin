"""v0.2 text indexing model tests.

Verifies stable chunk ID derivation, point-in-time indexing request requirements,
model-versioned embedding keys, and chunk-security link identity separation.
"""

from __future__ import annotations

from datetime import UTC, datetime

from margin.vector.models import (
    ChunkSecurityLink,
    EmbeddingKey,
    IndexingRequest,
    SourceLocator,
    TrustLevel,
    make_stable_chunk_id,
)


def test_stable_chunk_id_uses_document_content_parser_and_index() -> None:
    """Stable chunk ID must be derived from document, content, parser, and index.

    Verifies that ``make_stable_chunk_id`` produces a deterministic hash from the
    document ID, content hash, parser version, and chunk index.
    """
    chunk_id = make_stable_chunk_id(
        document_id="doc-1",
        content_hash="sha256:abc",
        parser_version="parser-v0.2.0",
        chunk_index=3,
    )

    assert chunk_id == "chk_c08c68de58773f3b84b9e44b8a5c5e15"


def test_indexing_request_requires_available_at_for_pit() -> None:
    """Indexing request must carry ``available_at`` for point-in-time retrieval.

    Verifies that an ``IndexingRequest`` with ``published_at=None`` still stores
    the ``available_at`` timestamp for PIT filtering.
    """
    request = IndexingRequest(
        event_id="event-1",
        snapshot_id="snapshot-1",
        content_hash="sha256:abc",
        document_type="news",
        published_at=None,
        available_at=datetime(2026, 6, 22, tzinfo=UTC),
        source_level="L4",
    )

    assert request.available_at.isoformat() == "2026-06-22T00:00:00+00:00"


def test_embedding_key_is_model_versioned() -> None:
    """Embedding key must be versioned by provider, model, and model version.

    Verifies that ``EmbeddingKey`` produces a deterministic hash incorporating the
    chunk ID, provider name, model name, and model version.
    """
    key = EmbeddingKey(
        chunk_id="chk-1",
        provider_name="openai-compatible",
        model_name="text-embedding-3-small",
        model_version="2026-06-01",
    )

    assert key.key_hash == "emb_d21ce8d71fb3ed968152e050944efa76"


def test_chunk_link_is_separate_from_chunk_identity() -> None:
    """Chunk-security links must be separate from chunk identity and locator anchors.

    Verifies that ``ChunkSecurityLink`` stores the security ID and confidence
    independently of the chunk, and that ``SourceLocator`` and ``TrustLevel``
    expose precise-anchor and value semantics correctly.
    """
    link = ChunkSecurityLink(
        chunk_id="chk-1",
        security_id="000001.SZ",
        link_type="mentioned",
        confidence=0.92,
    )

    assert link.security_id == "000001.SZ"
    assert link.confidence == 0.92
    assert SourceLocator(page=1, quote_span=(10, 20)).has_precise_anchor
    assert TrustLevel.UNTRUSTED_SOURCE_CONTENT.value == "untrusted_source_content"
