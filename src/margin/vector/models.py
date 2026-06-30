"""Data models for the text indexing layer: Chunk and retrieval results.

Defines the core data structures used by the vector indexing pipeline,
including document chunk metadata, source locator fields, and scored
retrieval candidates.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from margin.news.models import SourceLevel, ensure_utc, utc_now

# ---------------------------------------------------------------------------
# Document types
# ---------------------------------------------------------------------------


class DocType(StrEnum):
    """Document category used to select chunking and retrieval strategies.

    Attributes:
        ANNUAL_REPORT: Annual financial report.
        QUARTERLY_REPORT: Quarterly financial report.
        FILING: Regulatory filing.
        NEWS: News article or press release.
        IR: Investor relations material.
        INDUSTRY_REPORT: Third-party industry research report.
        USER_NOTE: User-authored note.
        UNKNOWN: Document type that could not be determined.
    """

    ANNUAL_REPORT = "annual_report"
    QUARTERLY_REPORT = "quarterly_report"
    FILING = "filing"
    NEWS = "news"
    IR = "ir"
    INDUSTRY_REPORT = "industry_report"
    USER_NOTE = "user_note"
    UNKNOWN = "unknown"


class TrustLevel(StrEnum):
    """Prompt-safety trust label attached to indexed chunks."""

    TRUSTED_OFFICIAL_CONTENT = "trusted_official_content"
    TRUSTED_STRUCTURED_DATA = "trusted_structured_data"
    UNTRUSTED_SOURCE_CONTENT = "untrusted_source_content"
    USER_SUPPLIED_CONTENT = "user_supplied_content"


class SourceLocator(BaseModel):
    """Source locator capable of replaying evidence to the original document."""

    page: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    section: str | None = None
    dom_path: str | None = None
    paragraph_index: int | None = None
    table_id: str | None = None
    row_id: str | None = None
    column_id: str | None = None
    quote_span: tuple[int, int] | None = None

    @property
    def has_precise_anchor(self) -> bool:
        """Return whether this locator can point back to a precise source region."""
        return any(
            value is not None
            for value in (
                self.page,
                self.bbox,
                self.dom_path,
                self.paragraph_index,
                self.table_id,
                self.row_id,
                self.quote_span,
            )
        )

    model_config = {"frozen": True}


class IndexingRequest(BaseModel):
    """Immutable request to index one persisted document event."""

    event_id: str
    snapshot_id: str
    content_hash: str
    document_type: str
    published_at: datetime | None
    available_at: datetime
    source_level: str

    @field_validator("published_at", "available_at")
    @classmethod
    def normalize_indexing_timestamp(cls, value: datetime | None) -> datetime | None:
        """Normalize indexing request timestamps to UTC."""
        return ensure_utc(value) if value is not None else None

    model_config = {"frozen": True}


class IndexedDocument(BaseModel):
    """Audit record for parser/chunker/embedding output of one document."""

    document_id: str
    event_id: str
    parser_version: str
    chunk_ids: tuple[str, ...]
    embedding_keys: tuple[str, ...]
    input_hash: str
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("created_at")
    @classmethod
    def normalize_indexed_document_created_at(cls, value: datetime) -> datetime:
        """Normalize audit timestamp to UTC."""
        return ensure_utc(value)

    model_config = {"frozen": True}


class EmbeddingKey(BaseModel):
    """Model-versioned embedding key for audit and replay."""

    chunk_id: str
    provider_name: str
    model_name: str
    model_version: str

    @property
    def key_hash(self) -> str:
        """Return deterministic embedding key hash."""
        payload = "|".join(
            [self.chunk_id, self.provider_name, self.model_name, self.model_version]
        )
        return "emb_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]

    model_config = {"frozen": True}


class ChunkSecurityLink(BaseModel):
    """Many-to-many relation between a chunk and a security."""

    chunk_id: str
    security_id: str
    link_type: str
    confidence: float = Field(ge=0.0, le=1.0)

    model_config = {"frozen": True}


def make_stable_chunk_id(
    *,
    document_id: str,
    content_hash: str,
    parser_version: str,
    chunk_index: int,
) -> str:
    """Create a symbol-independent stable chunk identifier.

    The identifier is derived from the document ID, content hash, parser
    version, and chunk index so that re-indexing the same document produces
    the same chunk IDs.

    Args:
        document_id: Identifier of the parent document.
        content_hash: Hash of the document content.
        parser_version: Version label of the parser that produced the chunk.
        chunk_index: Zero-based position of the chunk within the document.

    Returns:
        A ``chk_``-prefixed stable identifier string.
    """
    payload = "|".join([document_id, content_hash, parser_version, str(chunk_index)])
    return "chk_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


# ---------------------------------------------------------------------------
# Chunk
# ---------------------------------------------------------------------------


class Chunk(BaseModel):
    """A single immutable document chunk with full metadata and source locators.

    A Chunk captures a slice of source content together with provenance metadata
    (document, symbol, timestamps, source URL, etc.) and structural locators
    (page, section, paragraph, table row, character span). It is the atomic unit
    stored by the vector index and returned in retrieval results.

    Attributes:
        chunk_id: Stable identifier derived from the document and chunk index.
        document_id: Identifier of the parent document.
        content: Plain-text content of the chunk.
        content_hash: SHA-256 hash of the content used for integrity checks.
        symbol: Optional security/ticker symbol associated with the source.
        source_level: Source reliability level.
        doc_type: Document category.
        published_at: Original publication timestamp in UTC.
        available_at: Timestamp when the content became available in UTC.
        source_url: Optional URL pointing to the original source.
        source_name: Optional human-readable source name.
        snapshot_id: Optional identifier of the captured web snapshot.
        snapshot_hash: Optional hash of the captured snapshot.
        page: Optional page number in the source document.
        section: Optional section or chapter name.
        paragraph_index: Optional paragraph sequence number.
        table_id: Optional table identifier.
        row_id: Optional table row identifier.
        quote_span: Optional (start, end) character span for direct quoting.
        embedding: Optional dense vector embedding as a tuple of floats.
        keywords: Optional BM25/keyword terms extracted from the chunk.
        chunk_index: Zero-based position of this chunk within the document.
        total_chunks: Total number of chunks produced for the document.
    """

    chunk_id: str
    document_id: str
    content: str
    content_hash: str
    symbol: str | None = None
    source_level: SourceLevel = SourceLevel.L4
    doc_type: DocType = DocType.UNKNOWN
    published_at: datetime = Field(default_factory=utc_now)
    available_at: datetime = Field(default_factory=utc_now)
    source_url: str | None = None
    source_name: str | None = None
    snapshot_id: str | None = None
    snapshot_hash: str | None = None
    page: int | None = None
    section: str | None = None
    paragraph_index: int | None = None
    table_id: str | None = None
    row_id: str | None = None
    quote_span: tuple[int, int] | None = None
    locator: SourceLocator = Field(default_factory=SourceLocator)
    trust_level: TrustLevel = TrustLevel.TRUSTED_OFFICIAL_CONTENT
    is_active: bool = True
    embedding: tuple[float, ...] | None = None
    keywords: tuple[str, ...] = Field(default_factory=tuple)
    chunk_index: int = 0
    total_chunks: int = 0

    model_config = {"frozen": True}

    @field_validator("published_at", "available_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        """Normalize timestamp metadata to UTC.

        Args:
            value: A datetime value provided for ``published_at`` or
                ``available_at``.

        Returns:
            The input datetime converted to UTC.
        """
        return ensure_utc(value)

    @property
    def has_locator(self) -> bool:
        """Return whether the chunk can be traced back to its original source.

        A chunk is considered locatable when it carries a source URL and at
        least one structural locator such as page, section, paragraph index,
        table id, row id, or character span.

        Returns:
            ``True`` if the chunk has enough provenance to locate it in the
            original source, otherwise ``False``.
        """
        structural_locator = (
            self.locator.has_precise_anchor
            or self.page is not None
            or bool(self.section)
            or self.paragraph_index is not None
            or bool(self.table_id)
            or bool(self.row_id)
            or self.quote_span is not None
        )
        return bool(self.source_url) and structural_locator


# ---------------------------------------------------------------------------
# Retrieval results
# ---------------------------------------------------------------------------


class RetrievalResult(BaseModel):
    """A single scored retrieval candidate returned by a search operation.

    Attributes:
        chunk: The retrieved document chunk.
        score: Final combined relevance score.
        vector_score: Dense vector similarity score.
        keyword_score: Sparse/BM25 keyword score.
        time_decay: Recency/time-decay component.
        source_quality: Source reliability/quality component.
        entity_match: Entity match score.
        rank: Final rank after reranking.
    """

    chunk: Chunk
    score: float = 0.0
    vector_score: float = 0.0
    keyword_score: float = 0.0
    time_decay: float = 0.0
    source_quality: float = 0.0
    entity_match: float = 0.0
    rank: int = 0

    model_config = {"frozen": True}


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------


def compute_chunk_hash(content: str) -> str:
    """Compute a deterministic, cross-document content hash for a chunk.

    Args:
        content: Plain-text chunk content.

    Returns:
        A ``sha256:``-prefixed hexadecimal digest of the content.
    """
    import hashlib

    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


def make_chunk(
    document_id: str,
    content: str,
    chunk_index: int = 0,
    total_chunks: int = 1,
    **kwargs: Any,
) -> Chunk:
    """Create a Chunk with auto-generated chunk_id and content_hash.

    Args:
        document_id: Identifier of the parent document.
        content: Plain-text content for the chunk.
        chunk_index: Zero-based position of this chunk within the document.
        total_chunks: Total number of chunks produced for the document.
        **kwargs: Additional Chunk fields, such as ``symbol``, ``doc_type``,
            ``embedding``, or ``keywords``.

    Returns:
        A frozen ``Chunk`` instance ready for storage or indexing.
    """
    import hashlib

    symbol = kwargs.get("symbol")
    identity = f"{document_id}:{chunk_index}:{symbol or ''}"
    chunk_id = "chk_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]

    if "embedding" in kwargs and kwargs["embedding"] is not None:
        kwargs["embedding"] = tuple(kwargs["embedding"])
    if "keywords" in kwargs:
        kwargs["keywords"] = tuple(kwargs["keywords"])

    return Chunk(
        chunk_id=chunk_id,
        document_id=document_id,
        content=content,
        content_hash=compute_chunk_hash(content),
        chunk_index=chunk_index,
        total_chunks=total_chunks,
        **kwargs,
    )
