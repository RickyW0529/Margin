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
    """Pluggable embedding provider supporting OpenAI-compatible and local models.."""

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
            name: str: .
            version: str: .
            dim: int: .
            embed_func: Callable[[str], list[float]] | None: .
            secret_ref: str | None: .

        Returns:
            None: .
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
        """Return ProviderRegistry-compatible metadata.

        Returns:
            ProviderDescriptor: .
        """
        return self._descriptor

    @property
    def name(self) -> str:
        """Return the provider name.

        Returns:
            str: .
        """
        return self._name

    @property
    def version(self) -> str:
        """Return the provider version.

        Returns:
            str: .
        """
        return self._version

    @property
    def dim(self) -> int:
        """Return the configured embedding dimension.

        Returns:
            int: .
        """
        return self._dim

    def embed(self, text: str) -> list[float]:
        """Generate an embedding vector for the given text.

        Args:
            text: str: .

        Returns:
            list[float]: .
        """
        vector = [float(value) for value in self._embed_func(text)]
        if len(vector) != self._dim:
            raise ValueError(f"Embedding dim mismatch: expected {self._dim}, got {len(vector)}")
        return vector

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a batch of texts.

        Args:
            texts: list[str]: .

        Returns:
            list[list[float]]: .
        """
        return [self.embed(t) for t in texts]

    def set_embed_func(self, func: Callable[[str], list[float]]) -> None:
        """Inject a real embedding model function.

        Args:
            func: Callable[[str], list[float]]: .

        Returns:
            None: .
        """
        self._embed_func = func

    def configure_secrets(self, secrets: dict[str, str]) -> None:
        """Receive resolved credentials from ProviderRegistry.

        Args:
            secrets: dict[str, str]: .

        Returns:
            None: .
        """
        self._secrets = dict(secrets)

    def healthcheck(self) -> HealthCheckResult:
        """Verify that the configured embedding function can serve vectors.

        Returns:
            HealthCheckResult: .
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

        Args:
            text: str: .

        Returns:
            list[float]: .
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
    """In-memory vector store with a pgvector / Qdrant-compatible interface.."""

    def __init__(self, dim: int = 256) -> None:
        """Initialize the vector store.

        Args:
            dim: int: .

        Returns:
            None: .
        """
        self._dim = dim
        self._chunks: dict[str, Chunk] = {}
        self._vectors: dict[str, tuple[float, ...]] = {}

    def upsert(self, chunk: Chunk, vector: list[float]) -> None:
        """Write or update a chunk and its vector.

        Args:
            chunk: Chunk: .
            vector: list[float]: .

        Returns:
            None: .
        """
        if len(vector) != self._dim:
            raise ValueError(f"Vector dim mismatch: expected {self._dim}, got {len(vector)}")
        self._chunks[chunk.chunk_id] = chunk
        self._vectors[chunk.chunk_id] = tuple(vector)

    def upsert_batch(self, items: list[tuple[Chunk, list[float]]]) -> int:
        """Batch-write chunks and vectors.

        Args:
            items: list[tuple[Chunk, list[float]]]: .

        Returns:
            int: .
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
            query_vector: list[float]: .
            top_k: int: .
            filters: dict[str, Any] | None: .

        Returns:
            list[tuple[Chunk, float]]: .
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
            chunk_id: str: .

        Returns:
            Chunk | None: .
        """
        return self._chunks.get(chunk_id)

    @property
    def size(self) -> int:
        """Return the number of chunks currently stored.

        Returns:
            int: .
        """
        return len(self._chunks)

    def clear(self) -> None:
        """Remove all chunks and vectors from the store.

        Returns:
            None: .
        """
        self._chunks.clear()
        self._vectors.clear()

    @staticmethod
    def _match_filters(chunk: Chunk, filters: dict[str, Any] | None) -> bool:
        """Check whether a chunk matches the provided metadata filters.

        Args:
            chunk: Chunk: .
            filters: dict[str, Any] | None: .

        Returns:
            bool: .
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
    """In-memory BM25 keyword index.."""

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        """Initialize the BM25 index.

        Args:
            k1: float: .
            b: float: .

        Returns:
            None: .
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
            chunk: Chunk: .

        Returns:
            None: .
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
            chunks: list[Chunk]: .

        Returns:
            int: .
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
            query: str: .
            top_k: int: .
            filters: dict[str, Any] | None: .

        Returns:
            list[tuple[Chunk, float]]: .
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
        """Return the number of chunks currently indexed.

        Returns:
            int: .
        """
        return len(self._docs)

    def clear(self) -> None:
        """Remove all indexed documents and reset statistics.

        Returns:
            None: .
        """
        self._docs.clear()
        self._term_freqs.clear()
        self._doc_freqs.clear()
        self._doc_lengths.clear()
        self._avg_length = 0.0

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Tokenize text for indexing.

        Args:
            text: str: .

        Returns:
            list[str]: .
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
    """Audit record for index operations.."""

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
    """Records in-memory index operations for auditing.."""

    def __init__(self) -> None:
        """Initialize an empty auditor.

        Returns:
            None: .
        """
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
            index_name: str: .
            index_version: str: .
            chunk_count: int: .
            vector_count: int: .
            keyword_count: int: .
            degraded: bool: .
            error: str | None: .

        Returns:
            IndexAuditRecord: .
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
            index_name: str: .
            index_version: str: .
            query_info: dict[str, Any]: .
            result_count: int: .
            degraded: bool: .
            error: str | None: .

        Returns:
            IndexAuditRecord: .
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
        """Return a copy of all recorded audit entries.

        Returns:
            list[IndexAuditRecord]: .
        """
        return list(self._records)


# ---------------------------------------------------------------------------
# Embedding pipeline
# ---------------------------------------------------------------------------


class EmbeddingPipeline:
    """Orchestrates embedding generation, vector storage, and keyword indexing.."""

    def __init__(
        self,
        embedding_provider: EmbeddingProvider | None = None,
        vector_store: VectorStore | None = None,
        bm25_index: BM25Index | None = None,
        auditor: IndexAuditor | None = None,
    ) -> None:
        """Initialize the pipeline.

        Args:
            embedding_provider: EmbeddingProvider | None: .
            vector_store: VectorStore | None: .
            bm25_index: BM25Index | None: .
            auditor: IndexAuditor | None: .

        Returns:
            None: .
        """
        self._provider = embedding_provider or EmbeddingProvider()
        self._vector_store = vector_store or VectorStore(dim=self._provider.dim)
        self._bm25_index = bm25_index or BM25Index()
        self._auditor = auditor or IndexAuditor()

    @property
    def provider(self) -> EmbeddingProvider:
        """Return the configured embedding provider.

        Returns:
            EmbeddingProvider: .
        """
        return self._provider

    @property
    def vector_store(self) -> VectorStore:
        """Return the configured vector store.

        Returns:
            VectorStore: .
        """
        return self._vector_store

    @property
    def bm25_index(self) -> BM25Index:
        """Return the configured BM25 keyword index.

        Returns:
            BM25Index: .
        """
        return self._bm25_index

    @property
    def auditor(self) -> IndexAuditor:
        """Return the configured index auditor.

        Returns:
            IndexAuditor: .
        """
        return self._auditor

    def index_chunks(self, chunks: list[Chunk]) -> int:
        """Embed and index a list of chunks in both vector and keyword stores.

        Args:
            chunks: list[Chunk]: .

        Returns:
            int: .
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
            query_text: str: .
            top_k: int: .
            filters: dict[str, Any] | None: .

        Returns:
            list[tuple[Chunk, float]]: .
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
            query: str: .
            top_k: int: .
            filters: dict[str, Any] | None: .

        Returns:
            list[tuple[Chunk, float]]: .
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
        a: list[float]: .
        b: list[float]: .

    Returns:
        float: .
    """
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
