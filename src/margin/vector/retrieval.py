"""Hybrid retrieval and reranking.

Implements the contracts defined in specs 04 section 3, architecture sections 7.3
(hybrid retrieval) and 7.4 (retrieval constraints), and plans 0403:
  0403.1 Hybrid retrieval fusion (vector + BM25 + time decay + source quality + entity match)
  0403.2 Reranker (optional RerankProvider reranking)
  0403.3 Retrieval constraints (code filter, point-in-time filter, document type filter,
        official-source priority, deduplication, locator output)
  0403.4 RetrievalTool interface (for invocation by the multi-agent layer in 06)

Hybrid retrieval score (architecture section 7.3):
  Score = w_v * VectorScore + w_k * BM25 + w_t * TimeDecay
        + w_s * SourceQuality + w_e * EntityMatch

Retrieval constraints (architecture section 7.4):
  - Must filter by stock symbol.
  - Must satisfy available_at <= decision_at.
  - May filter by document type.
  - Prefer official evidence.
  - Deduplicate identical facts.
  - Output must include page numbers or original-text locators.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Callable
from datetime import datetime
from typing import Any

from pydantic import BaseModel, field_validator

from margin.news.models import SourceLevel, ensure_utc
from margin.vector.embedding import EmbeddingPipeline
from margin.vector.models import Chunk, RetrievalResult
from margin.vector.persistent_pipeline import PersistentEmbeddingPipeline

# ---------------------------------------------------------------------------
# Retrieval constraints
# ---------------------------------------------------------------------------


class SearchConstraints(BaseModel):
    """Constraints applied during retrieval (architecture section 7.4).

    Attributes:
        symbol: Stock symbol to filter by. Required for all retrieval calls.
        decision_at: Point in time at which the decision is made. Only chunks with
            available_at <= decision_at are returned.
        doc_types: Optional tuple of document types to include.
        prefer_official: Whether to boost official evidence sources.
        dedup: Whether to remove duplicate facts based on content hash.
        require_locator: Whether to drop chunks that lack a page or text locator.
    """

    symbol: str | None = None
    security_ids: tuple[str, ...] | None = None
    decision_at: datetime | None = None
    doc_types: tuple[str, ...] | None = None
    prefer_official: bool = True
    dedup: bool = True
    require_locator: bool = True

    model_config = {"frozen": True}

    @field_validator("decision_at")
    @classmethod
    def normalize_decision_at(cls, value: datetime | None) -> datetime | None:
        """Normalize the point-in-time constraint to UTC.

        Args:
            value: A datetime or None.

        Returns:
            The input datetime normalized to UTC, or None if no value was provided.
        """
        return ensure_utc(value) if value is not None else None


# ---------------------------------------------------------------------------
# Hybrid retrieval weights
# ---------------------------------------------------------------------------


class HybridWeights(BaseModel):
    """Fusion weights for hybrid retrieval (architecture section 7.3).

    Attributes:
        vector: Weight for the dense vector similarity score.
        keyword: Weight for the sparse BM25 keyword score.
        time_decay: Weight for the recency-based time decay score.
        source_quality: Weight for the source authority score.
        entity_match: Weight for the symbol/entity match score.
    """

    vector: float = 0.35
    keyword: float = 0.25
    time_decay: float = 0.15
    source_quality: float = 0.15
    entity_match: float = 0.10

    model_config = {"frozen": True}

    @property
    def total(self) -> float:
        """Return the sum of all component weights.

        Returns:
            The total weight value.
        """
        return (
            self.vector
            + self.keyword
            + self.time_decay
            + self.source_quality
            + self.entity_match
        )


# ---------------------------------------------------------------------------
# Hybrid retriever
# ---------------------------------------------------------------------------


class HybridRetriever:
    """Hybrid retriever that fuses vector search with keyword search.

    Scoring formula (architecture section 7.3):
      Score = w_v * VectorScore + w_k * BM25 + w_t * TimeDecay
            + w_s * SourceQuality + w_e * EntityMatch

    Retrieval constraints (architecture section 7.4):
      - Filter by stock symbol.
      - Require available_at <= decision_at.
      - Optionally filter by document type.
      - Prefer official evidence.
      - Deduplicate identical facts.
      - Require output locators.

    Attributes:
        _pipeline: Embedding pipeline providing vector and keyword search.
        _weights: Component weights for score fusion.
        _time_decay_days: Exponential decay scale in days.
    """

    def __init__(
        self,
        pipeline: EmbeddingPipeline,
        embedding_provider: Any | None = None,
        weights: HybridWeights | None = None,
        time_decay_days: float = 90.0,
    ) -> None:
        """Initialize the hybrid retriever.

        Args:
            pipeline: Embedding pipeline used for vector and keyword retrieval.
            weights: Optional fusion weights. Defaults to HybridWeights() when omitted.
            time_decay_days: Scale for the exponential time decay. Defaults to 90 days.
        """
        if embedding_provider is not None and hasattr(pipeline, "search_vector"):
            self._pipeline = PersistentEmbeddingPipeline(
                embedding_provider=embedding_provider,
                repository=pipeline,
            )
        else:
            self._pipeline = pipeline
        self._weights = weights or HybridWeights()
        self._time_decay_days = time_decay_days

    def search(
        self,
        query: str,
        top_k: int = 10,
        constraints: SearchConstraints | None = None,
        security_ids: tuple[str, ...] | None = None,
        decision_at: datetime | None = None,
    ) -> list[RetrievalResult]:
        """Execute hybrid retrieval and return a fused, ranked result list.

        Args:
            query: Query text.
            top_k: Number of top results to return.
            constraints: Retrieval constraints. A symbol and decision_at are required.

        Returns:
            A list of RetrievalResult objects sorted by fused score in descending order.

        Raises:
            ValueError: If constraints.symbol is missing or empty.
            ValueError: If constraints.decision_at is None.
        """
        constraints = constraints or SearchConstraints()
        if security_ids is not None or decision_at is not None:
            resolved_security_ids = security_ids or constraints.security_ids
            resolved_symbol = (
                resolved_security_ids or (constraints.symbol,)
            )[0]
            constraints = constraints.model_copy(
                update={
                    "security_ids": resolved_security_ids,
                    "symbol": resolved_symbol,
                    "decision_at": decision_at or constraints.decision_at,
                }
            )
        if not constraints.symbol and not constraints.security_ids:
            raise ValueError("symbol is required for retrieval")
        if constraints.decision_at is None:
            raise ValueError("decision_at is required for retrieval")

        fetch_k = top_k * 3
        filters = self._build_filters(constraints)

        try:
            vector_results = self._pipeline.vector_search(query, fetch_k, filters)
        except Exception:
            vector_results = []
        keyword_results = self._pipeline.keyword_search(query, fetch_k, filters)

        merged = self._merge_and_score(
            query, vector_results, keyword_results, constraints
        )

        if constraints.prefer_official:
            merged = self._boost_official(merged)

        if constraints.dedup:
            merged = self._dedup_results(merged)

        return [
            result.model_copy(update={"rank": index + 1})
            for index, result in enumerate(merged[:top_k])
        ]

    def _build_filters(self, constraints: SearchConstraints) -> dict[str, Any]:
        """Build metadata filters for the underlying search pipeline.

        Args:
            constraints: Retrieval constraints containing symbol and document types.

        Returns:
            A dictionary of metadata filters.
        """
        filters: dict[str, Any] = {}
        if constraints.symbol:
            filters["symbol"] = constraints.symbol
        if constraints.security_ids:
            filters["security_ids"] = constraints.security_ids
        if constraints.decision_at:
            filters["decision_at"] = constraints.decision_at
        if constraints.doc_types:
            filters["doc_type"] = constraints.doc_types
        return filters

    def _merge_and_score(
        self,
        query: str,
        vector_results: list[tuple[Chunk, float]],
        keyword_results: list[tuple[Chunk, float]],
        constraints: SearchConstraints,
    ) -> list[RetrievalResult]:
        """Merge vector and keyword results and compute fused retrieval scores.

        Args:
            query: Original query text.
            vector_results: List of (chunk, vector_score) tuples from dense retrieval.
            keyword_results: List of (chunk, keyword_score) tuples from BM25 retrieval.
            constraints: Active retrieval constraints.

        Returns:
            A ranked list of RetrievalResult objects.
        """
        chunk_map: dict[str, tuple[Chunk, float, float]] = {}

        for chunk, vscore in vector_results:
            chunk_map[chunk.chunk_id] = (chunk, vscore, 0.0)

        for chunk, kscore in keyword_results:
            if chunk.chunk_id in chunk_map:
                _, vs, _ = chunk_map[chunk.chunk_id]
                chunk_map[chunk.chunk_id] = (chunk, vs, kscore)
            else:
                chunk_map[chunk.chunk_id] = (chunk, 0.0, kscore)

        results: list[RetrievalResult] = []
        for chunk, vscore, kscore in chunk_map.values():
            if _normalize(vscore) == 0.0 and _normalize(kscore) == 0.0:
                continue
            if ensure_utc(chunk.available_at) > constraints.decision_at:
                continue
            if constraints.require_locator and not chunk.has_locator:
                continue

            time_score = self._time_decay(chunk, constraints.decision_at)
            quality_score = self._source_quality(chunk)
            entity_score = self._entity_match(chunk, constraints)

            fused_score = (
                self._weights.vector * _normalize(vscore)
                + self._weights.keyword * _normalize(kscore)
                + self._weights.time_decay * time_score
                + self._weights.source_quality * quality_score
                + self._weights.entity_match * entity_score
            )

            results.append(
                RetrievalResult(
                    chunk=chunk,
                    score=fused_score,
                    vector_score=vscore,
                    keyword_score=kscore,
                    time_decay=time_score,
                    source_quality=quality_score,
                    entity_match=entity_score,
                )
            )

        results.sort(key=lambda r: r.score, reverse=True)
        return results

    def _time_decay(self, chunk: Chunk, decision_at: datetime) -> float:
        """Compute the exponential time decay score.

        The score decreases as the age of the chunk relative to the decision point increases.

        Args:
            chunk: Candidate chunk containing published_at.
            decision_at: Decision point used as the reference time.

        Returns:
            A float in [0, 1] representing the recency score.
        """
        age_days = (
            ensure_utc(decision_at) - ensure_utc(chunk.published_at)
        ).total_seconds() / 86400
        if age_days < 0:
            age_days = 0
        return math.exp(-age_days / self._time_decay_days)

    def _source_quality(self, chunk: Chunk) -> float:
        """Compute the source authority score based on the chunk's source level.

        Args:
            chunk: Candidate chunk containing source_level.

        Returns:
            Authority score where L1=1.0, L2=0.8, L3=0.6, L4=0.4, L5=0.2.
            Unknown levels default to 0.3.
        """
        scores = {
            SourceLevel.L1: 1.0,
            SourceLevel.L2: 0.8,
            SourceLevel.L3: 0.6,
            SourceLevel.L4: 0.4,
            SourceLevel.L5: 0.2,
        }
        return scores.get(chunk.source_level, 0.3)

    def _entity_match(self, chunk: Chunk, constraints: SearchConstraints) -> float:
        """Compute the entity match score for the requested symbol.

        Args:
            chunk: Candidate chunk containing symbol.
            constraints: Retrieval constraints containing the target symbol.

        Returns:
            1.0 if the chunk symbol matches the constraint symbol, 0.0 otherwise.
            Returns 0.5 when no symbol constraint is provided.
        """
        if not constraints.symbol:
            return 0.5
        return 1.0 if chunk.symbol == constraints.symbol else 0.0

    def _boost_official(self, results: list[RetrievalResult]) -> list[RetrievalResult]:
        """Boost official evidence sources (L1-L3) and re-rank by score.

        Args:
            results: List of retrieval results to boost.

        Returns:
            The result list with official sources boosted and re-sorted.
        """
        boosted: list[RetrievalResult] = []
        for result in results:
            if result.chunk.source_level <= SourceLevel.L3:
                boosted.append(
                    result.model_copy(update={"score": result.score + 0.05})
                )
            else:
                boosted.append(result)
        boosted.sort(key=lambda r: r.score, reverse=True)
        return boosted

    def _dedup_results(self, results: list[RetrievalResult]) -> list[RetrievalResult]:
        """Remove duplicate facts based on normalized content hash.

        Args:
            results: List of retrieval results to deduplicate.

        Returns:
            The deduplicated result list preserving the original ranking order.
        """
        seen_hashes: set[str] = set()
        unique: list[RetrievalResult] = []
        for result in results:
            normalized = re.sub(r"\s+", " ", result.chunk.content).strip().casefold()
            content_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
            if content_hash in seen_hashes:
                continue
            seen_hashes.add(content_hash)
            unique.append(result)
        return unique


# ---------------------------------------------------------------------------
# Reranker
# ---------------------------------------------------------------------------


class Reranker:
    """Result reranker using an optional reranking provider (architecture section 7.1).

    The MVP ships with a simple cross-encoder-style fallback based on term coverage.
    Production deployments should inject a real model via set_rerank_func.

    Attributes:
        _rerank_func: Callable that scores (query, content) relevance.
    """

    def __init__(
        self,
        rerank_func: Callable[[str, str], float] | None = None,
    ) -> None:
        """Initialize the reranker.

        Args:
            rerank_func: Optional function accepting (query, content) and returning a float.
                Defaults to the built-in simple reranker when omitted.
        """
        self._rerank_func = rerank_func or self._simple_rerank

    def set_rerank_func(self, func: Callable[[str, str], float]) -> None:
        """Inject a real reranking model function.

        Args:
            func: Callable that takes (query, content) and returns a relevance score.
        """
        self._rerank_func = func

    def rerank(
        self,
        query: str,
        results: list[RetrievalResult],
        top_k: int | None = None,
    ) -> list[RetrievalResult]:
        """Rerank retrieval results.

        Args:
            query: Original query text.
            results: Retrieval results to rerank.
            top_k: Number of results to return. Defaults to all results when None.

        Returns:
            A list of RetrievalResult objects reranked by fused score in descending order.
        """
        scored: list[tuple[RetrievalResult, float]] = []
        for result in results:
            rerank_score = self._rerank_func(query, result.chunk.content)
            final_score = 0.7 * result.score + 0.3 * _normalize(rerank_score)
            scored.append((result, final_score))

        scored.sort(key=lambda x: x[1], reverse=True)

        k = top_k or len(scored)
        reranked: list[RetrievalResult] = []
        for i, (result, final_score) in enumerate(scored[:k]):
            reranked.append(
                RetrievalResult(
                    chunk=result.chunk,
                    score=final_score,
                    vector_score=result.vector_score,
                    keyword_score=result.keyword_score,
                    time_decay=result.time_decay,
                    source_quality=result.source_quality,
                    entity_match=result.entity_match,
                    rank=i + 1,
                )
            )
        return reranked

    @staticmethod
    def _simple_rerank(query: str, content: str) -> float:
        """Simple fallback reranker based on query term coverage in content.

        Args:
            query: Query text.
            content: Document content to score.

        Returns:
            The fraction of query terms found in the content, in [0, 1].
        """
        import re

        query_terms = set(re.findall(r"[\u4e00-\u9fff]|[a-z]+|\d+", query.lower()))
        if not query_terms:
            return 0.0
        content_lower = content.lower()
        matched = sum(1 for term in query_terms if term in content_lower)
        return matched / len(query_terms)


# ---------------------------------------------------------------------------
# RetrievalTool (invoked by the multi-agent layer in 06)
# ---------------------------------------------------------------------------


class RetrievalTool:
    """Unified retrieval interface exposed to multi-agent research workflows.

    Implements architecture section 11.1 RetrievalTool. It wraps hybrid retrieval,
    optional reranking, and constraint enforcement behind a simple search method.

    Example:
        tool = RetrievalTool(pipeline)
        results = tool.search(
            query="平安银行经营现金流",
            symbol="000001.SZ",
            decision_at=datetime(2026, 6, 18),
            top_k=5,
        )

    Attributes:
        _pipeline: Embedding pipeline used by the retriever.
        _retriever: HybridRetriever instance.
        _reranker: Reranker instance.
        _use_rerank: Whether to rerank results before returning them.
    """

    def __init__(
        self,
        pipeline: EmbeddingPipeline,
        retriever: HybridRetriever | None = None,
        reranker: Reranker | None = None,
        use_rerank: bool = True,
    ) -> None:
        """Initialize the retrieval tool.

        Args:
            pipeline: Embedding pipeline for vector and keyword search.
            retriever: Optional HybridRetriever instance.
            reranker: Optional Reranker instance.
            use_rerank: Whether to apply reranking. Defaults to True.
        """
        self._pipeline = pipeline
        self._retriever = retriever or HybridRetriever(pipeline)
        self._reranker = reranker or Reranker()
        self._use_rerank = use_rerank

    def search(
        self,
        query: str,
        symbol: str | None = None,
        decision_at: datetime | None = None,
        doc_types: list[str] | None = None,
        top_k: int = 10,
        prefer_official: bool = True,
    ) -> list[RetrievalResult]:
        """Execute retrieval and return evidence chunks with locators.

        All retrieval constraints are enforced:
        - Filter by stock symbol.
        - Require available_at <= decision_at.
        - Optionally filter by document type.
        - Prefer official evidence.
        - Deduplicate identical facts.
        - Require output locators.

        Args:
            query: Query text.
            symbol: Stock symbol. Required.
            decision_at: Decision point for point-in-time filtering. Required.
            doc_types: Optional list of document types to include.
            top_k: Number of top results to return.
            prefer_official: Whether to boost official evidence sources.

        Returns:
            A list of RetrievalResult objects ranked by relevance.

        Raises:
            ValueError: If symbol is missing or empty.
            ValueError: If decision_at is None.
        """
        if not symbol:
            raise ValueError("symbol is required for retrieval")
        if decision_at is None:
            raise ValueError("decision_at is required for retrieval")

        constraints = SearchConstraints(
            symbol=symbol,
            decision_at=decision_at,
            doc_types=doc_types,
            prefer_official=prefer_official,
            dedup=True,
            require_locator=True,
        )

        results = self._retriever.search(query, top_k * 2, constraints)

        if self._use_rerank and results:
            try:
                results = self._reranker.rerank(query, results, top_k)
            except Exception:
                results = results[:top_k]

        return results[:top_k]

    def search_by_symbol(
        self,
        symbol: str,
        query: str = "",
        decision_at: datetime | None = None,
        top_k: int = 10,
    ) -> list[RetrievalResult]:
        """Retrieve results filtered by stock symbol (architecture section 7.4).

        Args:
            symbol: Stock symbol. Required.
            query: Query text. Defaults to an empty string.
            decision_at: Decision point for point-in-time filtering. Required.
            top_k: Number of top results to return.

        Returns:
            A list of RetrievalResult objects filtered by symbol.
        """
        return self.search(
            query=query,
            symbol=symbol,
            decision_at=decision_at,
            top_k=top_k,
        )


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _normalize(score: float) -> float:
    """Clamp a score to the [0, 1] range.

    Args:
        score: Raw score value.

    Returns:
        The score clamped between 0.0 and 1.0.
    """
    if score <= 0:
        return 0.0
    if score >= 1:
        return 1.0
    return score
