"""PostgreSQL-backed pipeline compatible with the hybrid retriever."""

from __future__ import annotations

import re
from typing import Any

from margin.vector.models import Chunk, EmbeddingKey
from margin.vector.repository import VectorRepository


class PersistentEmbeddingPipeline:
    """Expose persistent chunks/embeddings through the retrieval pipeline API.."""

    def __init__(
        self,
        *,
        embedding_provider: Any,
        repository: VectorRepository,
    ) -> None:
        """Initialize the persistent embedding pipeline.

        Args:
            embedding_provider: Any: .
            repository: VectorRepository: .

        Returns:
            None: .
        """
        self._embedding_provider = embedding_provider
        self._repository = repository

    def vector_search(
        self,
        query_text: str,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[tuple[Chunk, float]]:
        """Search persisted embeddings using a vectorized query.

        Args:
            query_text: str: .
            top_k: int: .
            filters: dict[str, Any] | None: .

        Returns:
            list[tuple[Chunk, float]]: .
        """
        resolved = filters or {}
        query_vector = self._embedding_provider.embed(query_text)
        doc_types = resolved.get("doc_type")
        if isinstance(doc_types, str):
            doc_types = (doc_types,)
        elif doc_types is not None:
            doc_types = tuple(str(value) for value in doc_types)
        return self._repository.search_vector(
            query_vector,
            top_k=top_k,
            symbol=resolved.get("symbol"),
            security_ids=resolved.get("security_ids"),
            decision_at=resolved.get("decision_at"),
            doc_types=doc_types,
        )

    def keyword_search(
        self,
        query: str,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[tuple[Chunk, float]]:
        """Search persisted chunks using token overlap as a keyword fallback.

        Args:
            query: str: .
            top_k: int: .
            filters: dict[str, Any] | None: .

        Returns:
            list[tuple[Chunk, float]]: .
        """
        resolved = filters or {}
        doc_types = resolved.get("doc_type")
        if isinstance(doc_types, str):
            doc_types = (doc_types,)
        elif doc_types is not None:
            doc_types = tuple(str(value) for value in doc_types)
        chunks = self._repository.list_chunks(
            symbol=resolved.get("symbol"),
            security_ids=resolved.get("security_ids"),
            decision_at=resolved.get("decision_at"),
            doc_types=doc_types,
        )
        query_tokens = set(_tokenize(query))
        scored = []
        for chunk in chunks:
            chunk_tokens = set(_tokenize(chunk.content))
            if not query_tokens or not chunk_tokens:
                continue
            overlap = len(query_tokens.intersection(chunk_tokens))
            if overlap:
                scored.append((chunk, overlap / len(query_tokens)))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:top_k]


def _tokenize(text: str) -> list[str]:
    """Tokenize text for the fallback keyword scorer.

    Args:
        text: str: .

    Returns:
        list[str]: .
    """
    return re.findall(r"[\u4e00-\u9fff]|[a-z]+|\d+", text.lower())


class PersistentIndexingPipeline:
    """Persistent indexing helper with atomic embedding batch validation.."""

    def __init__(
        self,
        *,
        repository: VectorRepository,
        embedding_provider: Any,
        embedding_dimension: int,
        batch_size: int = 64,
    ) -> None:
        """Initialize the persistent indexing pipeline.

        Args:
            repository: VectorRepository: .
            embedding_provider: Any: .
            embedding_dimension: int: .
            batch_size: int: .

        Returns:
            None: .
        """
        self.repository = repository
        self.embedding_provider = embedding_provider
        self.embedding_dimension = embedding_dimension
        self.batch_size = batch_size

    def embed_and_persist(self, chunks: list[Chunk]) -> list[str]:
        """Embed chunks and persist vectors only after the whole batch validates.

        Args:
            chunks: list[Chunk]: .

        Returns:
            list[str]: .
        """
        embedding_keys: list[str] = []
        provider_name = str(getattr(self.embedding_provider, "name", "embedding"))
        model_name = str(getattr(self.embedding_provider, "model_name", provider_name))
        model_version = str(getattr(self.embedding_provider, "version", "unknown"))
        for start in range(0, len(chunks), self.batch_size):
            batch = chunks[start : start + self.batch_size]
            vectors = self.embedding_provider.embed_batch([chunk.content for chunk in batch])
            bad_indexes = [
                start + index
                for index, vector in enumerate(vectors)
                if len(vector) != self.embedding_dimension
            ]
            if bad_indexes:
                raise ValueError(
                    "Embedding dimension mismatch at batch indexes "
                    f"{bad_indexes}; expected {self.embedding_dimension}"
                )
            self.repository.upsert_embeddings(
                [(chunk.chunk_id, vector) for chunk, vector in zip(batch, vectors, strict=True)],
                provider_name=provider_name,
                model_name=model_name,
                model_version=model_version,
            )
            embedding_keys.extend(
                EmbeddingKey(
                    chunk_id=chunk.chunk_id,
                    provider_name=provider_name,
                    model_name=model_name,
                    model_version=model_version,
                ).key_hash
                for chunk in batch
            )
        return embedding_keys
