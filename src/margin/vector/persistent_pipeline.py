"""PostgreSQL-backed pipeline compatible with the hybrid retriever."""

from __future__ import annotations

import re
from typing import Any

from margin.vector.models import Chunk
from margin.vector.repository import VectorRepository


class PersistentEmbeddingPipeline:
    """Expose persistent chunks/embeddings through the retrieval pipeline API."""

    def __init__(
        self,
        *,
        embedding_provider: Any,
        repository: VectorRepository,
    ) -> None:
        self._embedding_provider = embedding_provider
        self._repository = repository

    def vector_search(
        self,
        query_text: str,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[tuple[Chunk, float]]:
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
            doc_types=doc_types,
        )

    def keyword_search(
        self,
        query: str,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[tuple[Chunk, float]]:
        resolved = filters or {}
        doc_types = resolved.get("doc_type")
        if isinstance(doc_types, str):
            doc_types = (doc_types,)
        elif doc_types is not None:
            doc_types = tuple(str(value) for value in doc_types)
        chunks = self._repository.list_chunks(
            symbol=resolved.get("symbol"),
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
    return re.findall(r"[\u4e00-\u9fff]|[a-z]+|\d+", text.lower())
