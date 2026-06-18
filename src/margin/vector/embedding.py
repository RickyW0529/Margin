"""Embedding and vector/keyword indexing.

Corresponds to specs 04 §3 interface contracts, architecture §7.1 data flow,
§8.1 EmbeddingProvider.
Corresponds to plans 0402:
  0402.1 EmbeddingProvider integration (OpenAI-compatible / local models)
  0402.2 pgvector vector storage (pluggable Qdrant interface)
  0402.3 Keyword indexing (BM25 / full-text index)
  0402.4 Index auditing and replay

Data flow (architecture §7.1):
  Raw documents → Parser → Chunker → Embedding → Vector DB / Keyword index
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Callable
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from margin.core.provider import (
    BaseProvider,
    HealthCheckResult,
    ProviderDescriptor,
    ProviderStatus,
    ProviderType,
)
from margin.news.models import utc_now
from margin.vector.models import Chunk

# ---------------------------------------------------------------------------
# Embedding Provider protocol
# ---------------------------------------------------------------------------


class EmbeddingProvider(BaseProvider):
    """Pluggable embedding provider supporting OpenAI-compatible and local models.

    The MVP ships with a deterministic hash-based pseudo-embedding for testing.
    Production usage should inject a real model via ``set_embed_func``.

    Attributes:
        descriptor: ProviderRegistry-compatible metadata.
        name: Provider name.
        version: Provider version string.
        dim: Embedding vector dimension.
    """

    def __init__(
        self,
        name: str = "hash_embedding",
        version: str = "1.0.0",
        dim: int = 256,
        embed_func: Callable[[str], list[float]] | None = None,
        secret_ref: str | None = None,
    ) -> None:
        """Initialize the embedding provider.

        Args:
            name: Provider identifier.
            version: Provider version.
            dim: Expected dimension of produced embedding vectors. Must be positive.
            embed_func: Optional function that turns text into a vector. Defaults to an
                internal hash-based implementation.
            secret_ref: Optional secret reference for resolving credentials.

        Raises:
            ValueError: If ``dim`` is not a positive integer.
        """
        if dim <= 0:
            raise ValueError("Embedding dimension must be positive")
        self._name = name
        self._version = version
        self._dim = dim
        self._embed_func = embed_func or self._hash_embed
        self._secret_ref = secret_ref
        self._secrets: dict[str, str] = {}
        self._descriptor = ProviderDescriptor(
            name=name,
            version=version,
            provider_type=ProviderType.EMBEDDING,
            capabilities=["embed", "embed_batch"],
            secret_refs=[secret_ref] if secret_ref else [],
            config={"dimension": dim},
        )

    @property
    def descriptor(self) -> ProviderDescriptor:
        """Return ProviderRegistry-compatible metadata."""
        return self._descriptor

    @property
    def name(self) -> str:
        """Return the provider name."""
        return self._name

    @property
    def version(self) -> str:
        """Return the provider version."""
        return self._version

    @property
    def dim(self) -> int:
        """Return the configured embedding dimension."""
        return self._dim

    def embed(self, text: str) -> list[float]:
        """Generate an embedding vector for the given text.

        Args:
            text: Input text to embed.

        Returns:
            A ``dim``-dimensional embedding vector.

        Raises:
            ValueError: If the produced vector length does not match ``dim``.
        """
        vector = [float(value) for value in self._embed_func(text)]
        if len(vector) != self._dim:
            raise ValueError(
                f"Embedding dim mismatch: expected {self._dim}, got {len(vector)}"
            )
        return vector

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a batch of texts.

        Args:
            texts: List of input texts.

        Returns:
            List of embedding vectors, one per input text.
        """
        return [self.embed(t) for t in texts]

    def set_embed_func(self, func: Callable[[str], list[float]]) -> None:
        """Inject a real embedding model function.

        Args:
            func: Callable accepting a string and returning a ``dim``-dimensional vector.
        """
        self._embed_func = func

    def configure_secrets(self, secrets: dict[str, str]) -> None:
        """Receive resolved credentials from ProviderRegistry.

        Args:
            secrets: Mapping of secret names to resolved values.
        """
        self._secrets = dict(secrets)

    def healthcheck(self) -> HealthCheckResult:
        """Verify that the configured embedding function can serve vectors.

        Returns:
            A ``HealthCheckResult`` indicating healthy or unhealthy status.
        """
        try:
            self.embed("healthcheck")
        except Exception as exc:
            return HealthCheckResult(
                provider_name=self._name,
                status=ProviderStatus.UNHEALTHY,
                checked_at=utc_now(),
                message=str(exc),
            )
        return HealthCheckResult(
            provider_name=self._name,
            status=ProviderStatus.HEALTHY,
            checked_at=utc_now(),
        )

    def _hash_embed(self, text: str) -> list[float]:
        """Deterministic hash-based pseudo-embedding for testing.

        The same text always produces the same vector, and different texts produce different
        vectors. It does **not** capture semantic similarity and is intended only for pipeline
        validation and environments without an external embedding API.

        Args:
            text: Input text.

        Returns:
            A unit-length pseudo-random embedding vector of length ``dim``.
        """
        vec = [0.0] * self._dim
        tokens = re.findall(r"[\u4e00-\u9fff]|[a-z]+|\d+", text.lower())
        for token in tokens:
            h = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)
            for i in range(self._dim):
                vec[i] += ((h >> (i % 32)) & 1) * 2.0 - 1.0

        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


# ---------------------------------------------------------------------------
# Vector store (in-memory pgvector-compatible)
# ---------------------------------------------------------------------------


class VectorStore:
    """In-memory vector store with a pgvector / Qdrant-compatible interface.

    Supports writes, vector similarity search, and metadata filtering. It can be swapped for a
    real pgvector backend once the Docker Compose environment is ready.

    Attributes:
        size: Number of chunks currently stored.
    """

    def __init__(self, dim: int = 256) -> None:
        """Initialize the vector store.

        Args:
            dim: Expected dimension of stored vectors.
        """
        self._dim = dim
        self._chunks: dict[str, Chunk] = {}
        self._vectors: dict[str, tuple[float, ...]] = {}

    def upsert(self, chunk: Chunk, vector: list[float]) -> None:
        """Write or update a chunk and its vector.

        Args:
            chunk: Chunk to store.
            vector: Embedding vector for the chunk.

        Raises:
            ValueError: If ``vector`` length does not match the store dimension.
        """
        if len(vector) != self._dim:
            raise ValueError(
                f"Vector dim mismatch: expected {self._dim}, got {len(vector)}"
            )
        self._chunks[chunk.chunk_id] = chunk
        self._vectors[chunk.chunk_id] = tuple(vector)

    def upsert_batch(self, items: list[tuple[Chunk, list[float]]]) -> int:
        """Batch-write chunks and vectors.

        Args:
            items: List of ``(chunk, vector)`` pairs.

        Returns:
            Number of items successfully stored. Items with dimension mismatches are skipped.
        """
        count = 0
        for chunk, vector in items:
            try:
                self.upsert(chunk, vector)
                count += 1
            except ValueError:
                continue
        return count

    def search(
        self,
        query_vector: list[float],
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[tuple[Chunk, float]]:
        """Search for chunks by vector similarity.

        Args:
            query_vector: Query embedding vector.
            top_k: Maximum number of results to return.
            filters: Optional metadata filters such as ``symbol``, ``source_level``,
                ``doc_type``, or ``document_id``.

        Returns:
            List of ``(Chunk, cosine_similarity)`` tuples sorted by similarity in descending
            order.
        """
        scored: list[tuple[Chunk, float]] = []

        for chunk_id, vector in self._vectors.items():
            chunk = self._chunks[chunk_id]
            if not self._match_filters(chunk, filters):
                continue
            sim = _cosine_similarity(query_vector, vector)
            scored.append((chunk, sim))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def get(self, chunk_id: str) -> Chunk | None:
        """Return the chunk with the given ID, or ``None`` if not found.

        Args:
            chunk_id: Unique chunk identifier.

        Returns:
            The matching ``Chunk`` or ``None``.
        """
        return self._chunks.get(chunk_id)

    @property
    def size(self) -> int:
        """Return the number of chunks currently stored."""
        return len(self._chunks)

    def clear(self) -> None:
        """Remove all chunks and vectors from the store."""
        self._chunks.clear()
        self._vectors.clear()

    @staticmethod
    def _match_filters(chunk: Chunk, filters: dict[str, Any] | None) -> bool:
        """Check whether a chunk matches the provided metadata filters.

        Args:
            chunk: Chunk to evaluate.
            filters: Metadata filters. Recognized keys include ``symbol``,
                ``source_level``, ``doc_type`` (supports a single value or collection),
                and ``document_id``. Unknown keys are matched against chunk attributes.

        Returns:
            ``True`` if the chunk matches all filters, otherwise ``False``.
        """
        if not filters:
            return True
        for key, value in filters.items():
            if key == "symbol":
                if chunk.symbol != value:
                    return False
            elif key == "source_level":
                if chunk.source_level != value:
                    return False
            elif key == "doc_type":
                allowed = value if isinstance(value, (list, tuple, set)) else (value,)
                if chunk.doc_type not in allowed:
                    return False
            elif key == "document_id":
                if chunk.document_id != value:
                    return False
            elif hasattr(chunk, key):
                if getattr(chunk, key) != value:
                    return False
        return True


# ---------------------------------------------------------------------------
# BM25 keyword index
# ---------------------------------------------------------------------------


class BM25Index:
    """In-memory BM25 keyword index.

    Tokenization supports Chinese characters (per-character) and English words.

    Attributes:
        size: Number of chunks currently indexed.
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        """Initialize the BM25 index.

        Args:
            k1: BM25 term frequency saturation parameter.
            b: BM25 length normalization parameter.
        """
        self._k1 = k1
        self._b = b
        self._docs: dict[str, Chunk] = {}
        self._term_freqs: dict[str, dict[str, int]] = {}
        self._doc_freqs: dict[str, int] = {}
        self._doc_lengths: dict[str, int] = {}
        self._avg_length: float = 0.0

    def upsert(self, chunk: Chunk) -> None:
        """Write or update a chunk in the keyword index.

        Args:
            chunk: Chunk to index. Existing entries are re-indexed.
        """
        previous_tf = self._term_freqs.get(chunk.chunk_id)
        if previous_tf is not None:
            for term in previous_tf:
                remaining = self._doc_freqs.get(term, 0) - 1
                if remaining > 0:
                    self._doc_freqs[term] = remaining
                else:
                    self._doc_freqs.pop(term, None)

        tokens = self._tokenize(chunk.content)
        self._docs[chunk.chunk_id] = chunk
        self._doc_lengths[chunk.chunk_id] = len(tokens)

        tf: dict[str, int] = {}
        for token in tokens:
            tf[token] = tf.get(token, 0) + 1
        self._term_freqs[chunk.chunk_id] = tf

        for term in tf:
            self._doc_freqs[term] = self._doc_freqs.get(term, 0) + 1

        total = sum(self._doc_lengths.values())
        self._avg_length = total / len(self._doc_lengths) if self._doc_lengths else 0.0

    def upsert_batch(self, chunks: list[Chunk]) -> int:
        """Batch-index chunks.

        Args:
            chunks: List of chunks to index.

        Returns:
            Number of chunks indexed.
        """
        for chunk in chunks:
            self.upsert(chunk)
        return len(chunks)

    def search(
        self,
        query: str,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[tuple[Chunk, float]]:
        """Search for chunks using BM25 keyword scoring.

        Args:
            query: Query text.
            top_k: Maximum number of results to return.
            filters: Optional metadata filters passed to ``VectorStore._match_filters``.

        Returns:
            List of ``(Chunk, bm25_score)`` tuples sorted by score in descending order.
        """
        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        n_docs = len(self._docs)
        scored: list[tuple[Chunk, float]] = []

        for chunk_id, chunk in self._docs.items():
            if not VectorStore._match_filters(chunk, filters):
                continue

            tf = self._term_freqs.get(chunk_id, {})
            doc_len = self._doc_lengths.get(chunk_id, 0)
            score = 0.0

            for term in query_tokens:
                if term not in tf:
                    continue
                df = self._doc_freqs.get(term, 0)
                idf = math.log((n_docs - df + 0.5) / (df + 0.5) + 1.0)
                term_freq = tf[term]
                avg = self._avg_length if self._avg_length > 0 else 1
                norm = 1 - self._b + self._b * (doc_len / avg)
                score += idf * (term_freq * (self._k1 + 1)) / (term_freq + self._k1 * norm)

            if score > 0:
                scored.append((chunk, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    @property
    def size(self) -> int:
        """Return the number of chunks currently indexed."""
        return len(self._docs)

    def clear(self) -> None:
        """Remove all indexed documents and reset statistics."""
        self._docs.clear()
        self._term_freqs.clear()
        self._doc_freqs.clear()
        self._doc_lengths.clear()
        self._avg_length = 0.0

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Tokenize text for indexing.

        English words are matched by alphabetic sequences; Chinese characters are matched
        individually.

        Args:
            text: Input text.

        Returns:
            List of lowercase tokens.
        """
        text = text.lower().strip()
        tokens: list[str] = []
        english_words = re.findall(r"[a-z]+", text)
        tokens.extend(english_words)
        chinese_chars = re.findall(r"[\u4e00-\u9fff]", text)
        tokens.extend(chinese_chars)
        return tokens


# ---------------------------------------------------------------------------
# Index auditing
# ---------------------------------------------------------------------------


class IndexAuditRecord(BaseModel):
    """Audit record for index operations.

    Captures index version and query metadata needed by a future persistent replay layer.

    Attributes:
        index_name: Name of the index involved.
        index_version: Version of the index at the time of the operation.
        operation: Operation type, e.g. ``upsert``, ``search``, or ``clear``.
        chunk_count: Number of chunks affected.
        query_info: Query parameters for search operations.
        result_count: Number of results returned by a search.
        vector_count: Number of chunks stored in the vector index.
        keyword_count: Number of chunks stored in the keyword index.
        degraded: Whether the operation completed in a degraded state.
        error: Optional error message.
        timestamp: UTC timestamp of the record.
    """

    index_name: str
    index_version: str
    operation: str  # upsert / search / clear
    chunk_count: int = 0
    query_info: dict[str, Any] = Field(default_factory=dict)
    result_count: int = 0
    vector_count: int = 0
    keyword_count: int = 0
    degraded: bool = False
    error: str | None = None
    timestamp: datetime = Field(default_factory=utc_now)

    model_config = {"frozen": True}


class IndexAuditor:
    """Records in-memory index operations for auditing."""

    def __init__(self) -> None:
        """Initialize an empty auditor."""
        self._records: list[IndexAuditRecord] = []

    def log_upsert(
        self,
        index_name: str,
        index_version: str,
        chunk_count: int,
        *,
        vector_count: int = 0,
        keyword_count: int = 0,
        degraded: bool = False,
        error: str | None = None,
    ) -> IndexAuditRecord:
        """Log an upsert/indexing operation.

        Args:
            index_name: Name of the index.
            index_version: Version of the index.
            chunk_count: Number of chunks processed.
            vector_count: Number of chunks stored as vectors.
            keyword_count: Number of chunks stored in the keyword index.
            degraded: Whether vector storage fell behind keyword indexing.
            error: Optional error message.

        Returns:
            The created audit record.
        """
        record = IndexAuditRecord(
            index_name=index_name,
            index_version=index_version,
            operation="upsert",
            chunk_count=chunk_count,
            vector_count=vector_count,
            keyword_count=keyword_count,
            degraded=degraded,
            error=error,
        )
        self._records.append(record)
        return record

    def log_search(
        self,
        index_name: str,
        index_version: str,
        query_info: dict[str, Any],
        result_count: int,
        *,
        degraded: bool = False,
        error: str | None = None,
    ) -> IndexAuditRecord:
        """Log a search operation.

        Args:
            index_name: Name of the index searched.
            index_version: Version of the index.
            query_info: Query parameters.
            result_count: Number of results returned.
            degraded: Whether the search completed in a degraded state.
            error: Optional error message.

        Returns:
            The created audit record.
        """
        record = IndexAuditRecord(
            index_name=index_name,
            index_version=index_version,
            operation="search",
            query_info=query_info,
            result_count=result_count,
            degraded=degraded,
            error=error,
        )
        self._records.append(record)
        return record

    @property
    def records(self) -> list[IndexAuditRecord]:
        """Return a copy of all recorded audit entries."""
        return list(self._records)


# ---------------------------------------------------------------------------
# Embedding pipeline
# ---------------------------------------------------------------------------


class EmbeddingPipeline:
    """Orchestrates embedding generation, vector storage, and keyword indexing.

    Data flow (architecture §7.1):
      Chunk → Embedding → Vector DB + Keyword index

    Example:
        pipeline = EmbeddingPipeline(provider, vector_store, bm25_index)
        pipeline.index_chunks(chunks)
        vector_results = pipeline.vector_search(query_vector)
        keyword_results = pipeline.keyword_search(query_text)

    Attributes:
        provider: The configured ``EmbeddingProvider``.
        vector_store: The configured ``VectorStore``.
        bm25_index: The configured ``BM25Index``.
        auditor: The configured ``IndexAuditor``.
    """

    def __init__(
        self,
        embedding_provider: EmbeddingProvider | None = None,
        vector_store: VectorStore | None = None,
        bm25_index: BM25Index | None = None,
        auditor: IndexAuditor | None = None,
    ) -> None:
        """Initialize the pipeline.

        Args:
            embedding_provider: Provider used to generate embeddings. Defaults to a hash-based
                provider.
            vector_store: Vector store. Defaults to an in-memory store sized to ``provider.dim``.
            bm25_index: Keyword index. Defaults to a new ``BM25Index``.
            auditor: Auditor used to record operations. Defaults to a new ``IndexAuditor``.
        """
        self._provider = embedding_provider or EmbeddingProvider()
        self._vector_store = vector_store or VectorStore(dim=self._provider.dim)
        self._bm25_index = bm25_index or BM25Index()
        self._auditor = auditor or IndexAuditor()

    @property
    def provider(self) -> EmbeddingProvider:
        """Return the configured embedding provider."""
        return self._provider

    @property
    def vector_store(self) -> VectorStore:
        """Return the configured vector store."""
        return self._vector_store

    @property
    def bm25_index(self) -> BM25Index:
        """Return the configured BM25 keyword index."""
        return self._bm25_index

    @property
    def auditor(self) -> IndexAuditor:
        """Return the configured index auditor."""
        return self._auditor

    def index_chunks(self, chunks: list[Chunk]) -> int:
        """Embed and index a list of chunks in both vector and keyword stores.

        Args:
            chunks: Chunks to index.

        Returns:
            Number of chunks successfully indexed in the keyword index.
        """
        if not chunks:
            return 0

        keyword_count = self._bm25_index.upsert_batch(chunks)
        vector_count = 0
        error: str | None = None
        try:
            vectors = self._provider.embed_batch([chunk.content for chunk in chunks])
            items = list(zip(chunks, vectors, strict=True))
            vector_count = self._vector_store.upsert_batch(items)
        except Exception as exc:
            error = str(exc)

        self._auditor.log_upsert(
            index_name="vector+bm25",
            index_version=self._provider.version,
            chunk_count=keyword_count,
            vector_count=vector_count,
            keyword_count=keyword_count,
            degraded=vector_count < keyword_count,
            error=error,
        )
        return keyword_count

    def vector_search(
        self,
        query_text: str,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[tuple[Chunk, float]]:
        """Search the vector store using an embedding of the query text.

        Args:
            query_text: Raw query text.
            top_k: Maximum number of results to return.
            filters: Optional metadata filters.

        Returns:
            List of ``(Chunk, cosine_similarity)`` tuples sorted by similarity.

        Raises:
            Exception: Re-raises any embedding or search error after logging a degraded
                audit record.
        """
        query_info = {
            "text": query_text[:100],
            "top_k": top_k,
            "filters": dict(filters or {}),
        }
        try:
            query_vector = self._provider.embed(query_text)
            results = self._vector_store.search(query_vector, top_k, filters)
        except Exception as exc:
            self._auditor.log_search(
                index_name="vector",
                index_version=self._provider.version,
                query_info=query_info,
                result_count=0,
                degraded=True,
                error=str(exc),
            )
            raise

        self._auditor.log_search(
            index_name="vector",
            index_version=self._provider.version,
            query_info=query_info,
            result_count=len(results),
        )
        return results

    def keyword_search(
        self,
        query: str,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[tuple[Chunk, float]]:
        """Search the BM25 keyword index.

        Args:
            query: Raw query text.
            top_k: Maximum number of results to return.
            filters: Optional metadata filters.

        Returns:
            List of ``(Chunk, bm25_score)`` tuples sorted by score.
        """
        results = self._bm25_index.search(query, top_k, filters)

        self._auditor.log_search(
            index_name="bm25",
            index_version="1.0.0",
            query_info={
                "query": query[:100],
                "top_k": top_k,
                "filters": dict(filters or {}),
            },
            result_count=len(results),
        )
        return results


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors.

    Args:
        a: First vector.
        b: Second vector. Must have the same length as ``a``.

    Returns:
        Cosine similarity in the range ``[-1, 1]``. Returns ``0.0`` if either vector has
        zero magnitude.
    """
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
