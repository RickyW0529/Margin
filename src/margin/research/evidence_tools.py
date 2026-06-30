"""Scoped RAG evidence retrieval tools for agent graph nodes."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from margin.evidence.package_builder import make_stable_evidence_id
from margin.news.models import ensure_utc
from margin.research.tools.definitions import (
    ToolCapability,
    ToolDefinition,
    ToolDefinitionRegistry,
)
from margin.vector.models import RetrievalResult


class RagEvidenceRetrievalTool(Protocol):
    """Protocol for vector-backed retrieval tools exposed to this adapter."""

    def search(
        self,
        *,
        query: str,
        symbol: str,
        decision_at: datetime,
        doc_types: list[str] | None,
        top_k: int,
        prefer_official: bool,
    ) -> list[RetrievalResult]:
        """Search for PIT-safe retrieval results."""


class EvidencePackageBuilderLike(Protocol):
    """Protocol for optional package builders used by RAG evidence tools."""

    def build(self, **kwargs: Any) -> Any:
        """Build and persist an EvidencePackage-like value."""


class RagEvidenceRetrieveInput(BaseModel):
    """Input schema for scoped RAG evidence retrieval."""

    security_id: str
    decision_at: datetime
    query: str = ""
    questions: tuple[str, ...] = ()
    evidence_gaps: tuple[str, ...] = ()
    doc_types: tuple[str, ...] = ()
    top_k: int = Field(default=8, ge=1, le=20)
    prefer_official: bool = True
    supplemental: bool = False
    build_package: bool = True
    news_bundle_id: str | None = None
    scope_hash: str | None = None

    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("decision_at")
    @classmethod
    def normalize_decision_at(cls, value: datetime) -> datetime:
        """Normalize decision timestamps to UTC."""
        return ensure_utc(value)


ScopeHashFactory = Callable[[dict[str, Any]], str]


def register_rag_evidence_tools(
    registry: ToolDefinitionRegistry,
    *,
    retrieval_tool: RagEvidenceRetrievalTool,
    package_builder: EvidencePackageBuilderLike | None = None,
    scope_hash_factory: ScopeHashFactory | None = None,
    name: str = "rag_evidence_retrieve",
    version: str = "rag-evidence-retrieve-v0.3.0",
) -> None:
    """Register a scoped RAG evidence retrieval tool.

    Args:
        registry: Tool registry to populate.
        retrieval_tool: PIT-safe vector retrieval adapter.
        package_builder: Optional EvidencePackage builder. When present and the
            call requests ``build_package=True``, retrieval output is frozen into
            the RAG evidence package system.
        scope_hash_factory: Optional deterministic scope hash provider.
        name: Tool name to register.
        version: Tool version string.
    """
    factory = scope_hash_factory or _default_scope_hash
    registry.register(
        ToolDefinition(
            name=name,
            capability=ToolCapability.EVIDENCE_RETRIEVE,
            version=version,
            description=(
                "Retrieve PIT-safe RAG evidence blocks for the scoped security "
                "and optionally freeze them as an EvidencePackage."
            ),
            input_model=RagEvidenceRetrieveInput,
            handler=lambda payload: _retrieve_rag_evidence(
                payload,
                retrieval_tool=retrieval_tool,
                package_builder=package_builder,
                scope_hash_factory=factory,
            ),
            estimated_result_bytes=32_768,
        )
    )


def _retrieve_rag_evidence(
    payload: dict[str, Any],
    *,
    retrieval_tool: RagEvidenceRetrievalTool,
    package_builder: EvidencePackageBuilderLike | None,
    scope_hash_factory: ScopeHashFactory,
) -> dict[str, Any]:
    """Run retrieval and return an agent/evidence-system friendly payload."""
    security_id = str(payload["security_id"])
    decision_at = ensure_utc(payload["decision_at"])
    questions = tuple(str(value) for value in payload.get("questions", ()))
    evidence_gaps = tuple(str(value) for value in payload.get("evidence_gaps", ()))
    query = _resolve_query(
        query=str(payload.get("query") or ""),
        questions=questions,
        evidence_gaps=evidence_gaps,
        supplemental=bool(payload.get("supplemental", False)),
    )
    doc_types = tuple(str(value) for value in payload.get("doc_types", ()))
    top_k = int(payload.get("top_k") or 8)
    results = retrieval_tool.search(
        query=query,
        symbol=security_id,
        decision_at=decision_at,
        doc_types=list(doc_types) if doc_types else None,
        top_k=top_k,
        prefer_official=bool(payload.get("prefer_official", True)),
    )

    scope_hash = str(payload.get("scope_hash") or scope_hash_factory(payload))
    package = None
    if package_builder is not None and bool(payload.get("build_package", True)):
        package = package_builder.build(
            security_id=security_id,
            decision_at=decision_at,
            questions=questions,
            retrieval_results=results,
            news_bundle_id=payload.get("news_bundle_id"),
            scope_hash=scope_hash,
        )

    evidence_ids = (
        tuple(str(value) for value in getattr(package, "evidence_ids", ()))
        if package is not None
        else tuple(
            make_stable_evidence_id(security_id, result.chunk)
            for result in results
        )
    )
    blocks = _evidence_blocks(
        security_id=security_id,
        results=results,
        package_evidence_ids=evidence_ids,
        filter_to_package=package is not None,
    )
    returned_evidence_ids = (
        evidence_ids
        if package is None
        else tuple(str(value) for value in getattr(package, "evidence_ids", ()))
    )
    quality_status = (
        str(getattr(package, "quality_status").value)
        if package is not None and hasattr(getattr(package, "quality_status"), "value")
        else str(getattr(package, "quality_status", "usable" if blocks else "abstain_required"))
    )
    coverage = (
        float(getattr(package, "coverage"))
        if package is not None and hasattr(package, "coverage")
        else (1.0 if blocks else 0.0)
    )
    return {
        "package_id": str(getattr(package, "package_id", "")) if package is not None else None,
        "version": getattr(package, "version", None) if package is not None else None,
        "security_id": security_id,
        "decision_at": decision_at.isoformat(),
        "scope_hash": scope_hash,
        "evidence_ids": list(returned_evidence_ids),
        "quality_status": quality_status,
        "coverage": coverage,
        "retrieval_audit_id": (
            str(getattr(package, "retrieval_audit_id"))
            if package is not None and getattr(package, "retrieval_audit_id", None)
            else None
        ),
        "retrieval": {
            "query": query,
            "questions": list(questions),
            "evidence_gaps": list(evidence_gaps),
            "supplemental": bool(payload.get("supplemental", False)),
            "top_k": top_k,
            "doc_types": list(doc_types),
            "result_count": len(results),
        },
        "evidence_blocks": blocks,
    }


def _resolve_query(
    *,
    query: str,
    questions: tuple[str, ...],
    evidence_gaps: tuple[str, ...],
    supplemental: bool,
) -> str:
    """Resolve the search text sent to the retriever."""
    stripped = query.strip()
    if stripped:
        return stripped
    if supplemental and evidence_gaps:
        return "\n".join(evidence_gaps)
    if questions:
        return "\n".join(questions)
    return "evidence retrieval"


def _evidence_blocks(
    *,
    security_id: str,
    results: list[RetrievalResult],
    package_evidence_ids: tuple[str, ...],
    filter_to_package: bool,
) -> list[dict[str, Any]]:
    """Serialize retrieval results into agent-ready evidence blocks."""
    default_ids = [
        make_stable_evidence_id(security_id, result.chunk)
        for result in results
    ]
    evidence_ids = (
        list(package_evidence_ids)
        if len(package_evidence_ids) == len(results)
        else default_ids
    )
    package_id_set = set(package_evidence_ids)
    blocks: list[dict[str, Any]] = []
    for index, (result, evidence_id) in enumerate(
        zip(results, evidence_ids, strict=True),
        start=1,
    ):
        if filter_to_package and evidence_id not in package_id_set:
            continue
        chunk = result.chunk
        blocks.append(
            {
                "rank": int(result.rank or index),
                "evidence_id": evidence_id,
                "chunk_id": chunk.chunk_id,
                "document_id": chunk.document_id,
                "source_url": chunk.source_url,
                "source_name": chunk.source_name,
                "source_level": int(chunk.source_level),
                "doc_type": str(chunk.doc_type.value),
                "content": chunk.content,
                "content_hash": chunk.content_hash,
                "score": float(result.score),
                "vector_score": float(result.vector_score),
                "keyword_score": float(result.keyword_score),
                "published_at": ensure_utc(chunk.published_at).isoformat(),
                "available_at": ensure_utc(chunk.available_at).isoformat(),
                "snapshot_id": chunk.snapshot_id,
                "snapshot_hash": chunk.snapshot_hash,
                "locator": _locator_payload(chunk),
            }
        )
    return blocks


def _locator_payload(chunk: Any) -> dict[str, Any]:
    """Return the source locator fields agents may cite."""
    locator = getattr(chunk, "locator", None)
    page = chunk.page if chunk.page is not None else getattr(locator, "page", None)
    section = chunk.section or getattr(locator, "section", None)
    paragraph_index = (
        chunk.paragraph_index
        if chunk.paragraph_index is not None
        else getattr(locator, "paragraph_index", None)
    )
    table_id = chunk.table_id or getattr(locator, "table_id", None)
    row_id = chunk.row_id or getattr(locator, "row_id", None)
    quote_span = chunk.quote_span or getattr(locator, "quote_span", None)
    return {
        "page": page,
        "section": section,
        "paragraph_index": paragraph_index,
        "table_id": table_id,
        "row_id": row_id,
        "quote_span": list(quote_span) if quote_span else None,
    }


def _default_scope_hash(payload: dict[str, Any]) -> str:
    """Compute a stable scope hash for one retrieval request."""
    relevant = {
        "security_id": payload.get("security_id"),
        "decision_at": ensure_utc(payload["decision_at"]).isoformat(),
        "query": payload.get("query") or "",
        "questions": list(payload.get("questions", ())),
        "evidence_gaps": list(payload.get("evidence_gaps", ())),
        "doc_types": list(payload.get("doc_types", ())),
        "supplemental": bool(payload.get("supplemental", False)),
    }
    encoded = json.dumps(
        relevant,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()
