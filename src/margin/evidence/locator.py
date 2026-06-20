"""Citation locator fields — multi-source location, WebSearch original verification,
and point-in-time checks.

Corresponds to spec 05 §4 citation locator fields and architecture §10.3 locator.
Corresponds to plan 0502:
    0502.1 Locator field model — unified locator field structure.
    0502.2 PDF / HTML / table differentiated location — populate fields by source type.
    0502.3 WebSearch original source verification — do not cite only search snippets.
    0502.4 Point-in-time check — every citation must satisfy available_at <= decision_at.

Citation locator fields (product §9.3):
    evidence_id / document_id / source_type / source_url / source_level
    / content_hash / published_at / available_at / retrieved_at
    / page / section / paragraph_index / table_id / row_id / quote_span

Requirements:
    - PDF: prefer page number, section, and character span.
    - HTML: prefer URL, title, paragraph index, and content hash.
    - Table: prefer table ID, row-column locator, and original file hash.
    - WebSearch results must land on an accessible original page or compliant snapshot,
      not only a search snippet.
    - Every citation must satisfy available_at <= decision_at.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from margin.evidence.models import Evidence
from margin.news.models import RawSnapshot, SourceLevel, ensure_utc

SnapshotResolver = Callable[[str], RawSnapshot | None]
"""Callable that resolves a snapshot ID to a RawSnapshot, or None if not found."""

# ---------------------------------------------------------------------------
# 0502.1 Source types
# ---------------------------------------------------------------------------


class SourceType(StrEnum):
    """Source type enumeration (product §9.3 source_type field)."""

    FILING_PDF = "filing_pdf"
    WEB_PAGE = "web_page"
    TABLE = "table"
    API_RECORD = "api_record"
    USER_FILE = "user_file"


# ---------------------------------------------------------------------------
# 0502.1 CitationLocator
# ---------------------------------------------------------------------------


class CitationLocator(BaseModel):
    """Citation locator fields (architecture §10.3 locator + product §9.3).

    Stores all information needed to trace a conclusion back to its original source.
    Immutable after persistence.

    Attributes:
        evidence_id: Unique identifier of the related evidence record.
        document_id: Identifier of the originating document.
        source_type: Source type enumeration.
        source_url: Optional URL of the original source.
        source_level: Source level priority (L1-L5).
        content_hash: Hash of the cited content.
        published_at: Publication timestamp (UTC).
        available_at: Availability timestamp (UTC).
        retrieved_at: Retrieval timestamp (UTC).
        page: Optional page number in the original document.
        section: Optional section name in the original document.
        paragraph_index: Optional paragraph index in the original document.
        table_id: Optional table identifier.
        row_id: Optional row identifier.
        quote_span: Optional character span tuple (start, end).
        snapshot_id: Optional snapshot identifier.
        snapshot_hash: Optional snapshot content hash.
    """

    evidence_id: str
    document_id: str
    source_type: SourceType = SourceType.WEB_PAGE
    source_url: str | None = None
    source_level: SourceLevel = SourceLevel.L4
    content_hash: str = ""
    published_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    available_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    page: int | None = None
    section: str | None = None
    paragraph_index: int | None = None
    table_id: str | None = None
    row_id: str | None = None
    quote_span: tuple[int, int] | None = None
    snapshot_id: str | None = None
    snapshot_hash: str | None = None

    model_config = {"frozen": True}

    @field_validator("published_at", "available_at", "retrieved_at")
    @classmethod
    def normalize_timestamps(cls, value: datetime) -> datetime:
        """Normalize timestamp fields to UTC.

        Args:
            value: A datetime value to normalize.

        Returns:
            The datetime normalized to UTC.
        """
        return ensure_utc(value)

    @property
    def is_locatable(self) -> bool:
        """Return whether the locator can trace back to the original source.

        Requires at least a source_url plus one structural locator field.

        Returns:
            True if both source_url and a structural locator are present.
        """
        has_structural = (
            self.page is not None
            or bool(self.section)
            or self.paragraph_index is not None
            or bool(self.table_id)
            or bool(self.row_id)
            or self.quote_span is not None
        )
        return bool(self.source_url) and has_structural

    @property
    def has_snapshot(self) -> bool:
        """Return whether the locator references an original snapshot.

        Returns:
            True if a snapshot_id is present.
        """
        return self.snapshot_id is not None

    @classmethod
    def from_evidence(cls, evidence: Evidence) -> CitationLocator:
        """Build a CitationLocator from an Evidence instance.

        Args:
            evidence: The evidence record to convert.

        Returns:
            A new CitationLocator instance.
        """
        source_type = (
            SourceType(evidence.source_type)
            if evidence.source_type in [t.value for t in SourceType]
            else SourceType.WEB_PAGE
        )
        return cls(
            evidence_id=evidence.evidence_id,
            document_id=evidence.document_id,
            source_type=source_type,
            source_url=evidence.source_url,
            source_level=evidence.source_level,
            content_hash=evidence.content_hash,
            published_at=evidence.published_at,
            available_at=evidence.available_at,
            retrieved_at=evidence.retrieved_at,
            page=evidence.page,
            section=evidence.section,
            paragraph_index=evidence.paragraph_index,
            table_id=evidence.table_id,
            row_id=evidence.row_id,
            quote_span=evidence.quote_span,
            snapshot_id=evidence.snapshot_id,
            snapshot_hash=evidence.snapshot_hash,
        )

    @classmethod
    def from_chunk(cls, chunk: Any) -> CitationLocator:
        """Build a CitationLocator from a Chunk (convenience method).

        Args:
            chunk: A Chunk object containing locator fields.

        Returns:
            A new CitationLocator instance.
        """
        ev = Evidence.from_chunk(chunk)
        return cls.from_evidence(ev)


# ---------------------------------------------------------------------------
# 0502.2 Differentiated locator population
# ---------------------------------------------------------------------------


def build_locator_from_pdf(
    chunk: Any,
    page: int | None = None,
    section: str | None = None,
    quote_span: tuple[int, int] | None = None,
) -> CitationLocator:
    """Build a locator for a PDF source: prefer page, section, and character span.

    Args:
        chunk: A Chunk object.
        page: Page number; uses parameter if provided, otherwise chunk.page.
        section: Section name; uses parameter if provided, otherwise chunk.section.
        quote_span: Character span; uses parameter if provided, otherwise chunk.quote_span.

    Returns:
        A CitationLocator configured for a PDF filing source.
    """
    ev = Evidence.from_chunk(chunk, source_type=SourceType.FILING_PDF.value)
    locator = CitationLocator.from_evidence(ev)
    return locator.model_copy(
        update={
            "source_type": SourceType.FILING_PDF,
            "page": page if page is not None else chunk.page,
            "section": section if section is not None else chunk.section,
            "quote_span": quote_span if quote_span is not None else chunk.quote_span,
        }
    )


def build_locator_from_html(
    chunk: Any,
    paragraph_index: int | None = None,
) -> CitationLocator:
    """Build a locator for an HTML source: prefer URL, title, paragraph index, content hash.

    Args:
        chunk: A Chunk object.
        paragraph_index: Paragraph index; uses parameter if provided, otherwise
            chunk.paragraph_index.

    Returns:
        A CitationLocator configured for a web page source.
    """
    ev = Evidence.from_chunk(chunk, source_type=SourceType.WEB_PAGE.value)
    locator = CitationLocator.from_evidence(ev)
    return locator.model_copy(
        update={
            "source_type": SourceType.WEB_PAGE,
            "paragraph_index": (
                paragraph_index
                if paragraph_index is not None
                else chunk.paragraph_index
            ),
            "page": None,
            "table_id": None,
            "row_id": None,
        }
    )


def build_locator_from_table(
    chunk: Any,
    table_id: str | None = None,
    row_id: str | None = None,
) -> CitationLocator:
    """Build a locator for a table source: prefer table ID, row locator, original file hash.

    Args:
        chunk: A Chunk object.
        table_id: Table identifier; uses parameter if provided, otherwise chunk.table_id.
        row_id: Row identifier; uses parameter if provided, otherwise chunk.row_id.

    Returns:
        A CitationLocator configured for a table source.
    """
    ev = Evidence.from_chunk(chunk, source_type=SourceType.TABLE.value)
    locator = CitationLocator.from_evidence(ev)
    return locator.model_copy(
        update={
            "source_type": SourceType.TABLE,
            "table_id": table_id if table_id is not None else chunk.table_id,
            "row_id": row_id if row_id is not None else chunk.row_id,
            "page": chunk.page,
            "quote_span": None,
        }
    )


# ---------------------------------------------------------------------------
# 0502.3 WebSearch original source verification
# ---------------------------------------------------------------------------


class WebSearchVerificationResult(BaseModel):
    """Result of a WebSearch original-source verification check.

    Attributes:
        evidence_id: Identifier of the evidence being verified.
        passed: Whether the verification passed.
        reason: Human-readable explanation of the outcome.
    """

    evidence_id: str
    passed: bool
    reason: str = ""

    model_config = {"frozen": True}


def verify_websearch_original(
    locator: CitationLocator,
    require_snapshot: bool = True,
    snapshot_resolver: SnapshotResolver | None = None,
) -> WebSearchVerificationResult:
    """Verify a WebSearch result lands on an original source (architecture §6.2.1: 0502.3).

    WebSearch results must point to an accessible original page or compliant snapshot,
    not only a search snippet.

    Args:
        locator: The citation locator to verify.
        require_snapshot: Whether a snapshot reference is required.
        snapshot_resolver: Optional lookup function for persisted raw snapshots.

    Returns:
        A WebSearchVerificationResult describing the outcome.
    """
    if locator.source_type != SourceType.WEB_PAGE:
        return WebSearchVerificationResult(
            evidence_id=locator.evidence_id,
            passed=True,
            reason="not a web_page source, skip",
        )

    if not locator.source_url:
        return WebSearchVerificationResult(
            evidence_id=locator.evidence_id,
            passed=False,
            reason="missing source_url — cannot verify web search original",
        )

    if require_snapshot and not locator.has_snapshot:
        return WebSearchVerificationResult(
            evidence_id=locator.evidence_id,
            passed=False,
            reason="web search result has no snapshot — cannot reference search snippet only",
        )

    if require_snapshot and snapshot_resolver is not None and locator.snapshot_id:
        snapshot = snapshot_resolver(locator.snapshot_id)
        if snapshot is None:
            return WebSearchVerificationResult(
                evidence_id=locator.evidence_id,
                passed=False,
                reason=f"web search snapshot '{locator.snapshot_id}' not found",
            )
        if snapshot.source_url != locator.source_url:
            return WebSearchVerificationResult(
                evidence_id=locator.evidence_id,
                passed=False,
                reason="web search snapshot URL does not match locator source_url",
            )
        if locator.snapshot_hash and snapshot.content_hash != locator.snapshot_hash:
            return WebSearchVerificationResult(
                evidence_id=locator.evidence_id,
                passed=False,
                reason="web search snapshot hash does not match locator snapshot_hash",
            )
        if snapshot.http_status is not None and snapshot.http_status >= 400:
            return WebSearchVerificationResult(
                evidence_id=locator.evidence_id,
                passed=False,
                reason=f"web search snapshot HTTP status is not accessible: {snapshot.http_status}",
            )

    if not locator.is_locatable:
        return WebSearchVerificationResult(
            evidence_id=locator.evidence_id,
            passed=False,
            reason="web search result is not locatable to original text",
        )

    return WebSearchVerificationResult(
        evidence_id=locator.evidence_id,
        passed=True,
        reason="web search original verified",
    )


# ---------------------------------------------------------------------------
# 0502.4 Point-in-time checks
# ---------------------------------------------------------------------------


class PointInTimeCheckResult(BaseModel):
    """Result of a point-in-time check.

    Attributes:
        evidence_id: Identifier of the evidence being checked.
        passed: Whether the check passed.
        reason: Human-readable explanation of the outcome.
        available_at: The availability timestamp used in the check.
        decision_at: The decision timestamp used in the check.
    """

    evidence_id: str
    passed: bool
    reason: str = ""
    available_at: datetime | None = None
    decision_at: datetime | None = None

    model_config = {"frozen": True}


def check_point_in_time(
    locator: CitationLocator,
    decision_at: datetime,
) -> PointInTimeCheckResult:
    """Point-in-time check (architecture §4.5: available_at <= decision_at).

    Every citation must satisfy available_at <= decision_at to prevent future-data leakage.

    Args:
        locator: The citation locator to check.
        decision_at: The decision timestamp.

    Returns:
        A PointInTimeCheckResult describing the outcome.
    """
    available = ensure_utc(locator.available_at)
    decision = ensure_utc(decision_at)

    if available <= decision:
        return PointInTimeCheckResult(
            evidence_id=locator.evidence_id,
            passed=True,
            reason="available_at <= decision_at",
            available_at=available,
            decision_at=decision,
        )

    return PointInTimeCheckResult(
        evidence_id=locator.evidence_id,
        passed=False,
        reason=f"lookahead: available_at={available} > decision_at={decision}",
        available_at=available,
        decision_at=decision,
    )


def check_locators_point_in_time(
    locators: list[CitationLocator],
    decision_at: datetime,
) -> tuple[list[CitationLocator], list[PointInTimeCheckResult]]:
    """Run point-in-time checks for a batch of locators.

    Args:
        locators: List of citation locators to check.
        decision_at: The decision timestamp.

    Returns:
        A tuple of (locators that passed, all check results).
    """
    passed_locators: list[CitationLocator] = []
    results: list[PointInTimeCheckResult] = []

    for locator in locators:
        result = check_point_in_time(locator, decision_at)
        results.append(result)
        if result.passed:
            passed_locators.append(locator)

    return passed_locators, results


# ---------------------------------------------------------------------------
# Comprehensive locator validation
# ---------------------------------------------------------------------------


class LocatorValidationResult(BaseModel):
    """Aggregated locator validation result.

    Attributes:
        evidence_id: Identifier of the evidence being validated.
        is_locatable: Whether the locator can trace back to the original source.
        pit_passed: Whether the point-in-time check passed.
        websearch_passed: Optional result of WebSearch verification (None if not checked).
        reasons: List of human-readable failure reasons.
    """

    evidence_id: str
    is_locatable: bool
    pit_passed: bool
    websearch_passed: bool | None = None
    reasons: list[str] = Field(default_factory=list)

    model_config = {"frozen": True}

    @property
    def all_passed(self) -> bool:
        """Return whether every validation check passed.

        Returns:
            True if locatable, point-in-time passed, and (when applicable) WebSearch
            verification passed.
        """
        if not self.is_locatable:
            return False
        if not self.pit_passed:
            return False
        if self.websearch_passed is not None and not self.websearch_passed:
            return False
        return True


def validate_locator(
    locator: CitationLocator,
    decision_at: datetime,
    check_websearch: bool = True,
    snapshot_resolver: SnapshotResolver | None = None,
) -> LocatorValidationResult:
    """Validate a citation locator comprehensively.

    Checks:
        1. is_locatable — original source can be located.
        2. point_in_time — available_at <= decision_at.
        3. websearch_original — WebSearch results land on original source
           (only for web_page type).

    Args:
        locator: The citation locator to validate.
        decision_at: The decision timestamp.
        check_websearch: Whether to run WebSearch original-source verification.
        snapshot_resolver: Optional lookup function for persisted raw snapshots.

    Returns:
        A LocatorValidationResult with all check outcomes.
    """
    reasons: list[str] = []

    if not locator.is_locatable:
        reasons.append("not locatable: missing source_url or structural locator")

    pit_result = check_point_in_time(locator, decision_at)
    if not pit_result.passed:
        reasons.append(pit_result.reason)

    websearch_passed: bool | None = None
    if check_websearch and locator.source_type == SourceType.WEB_PAGE:
        ws_result = verify_websearch_original(
            locator,
            snapshot_resolver=snapshot_resolver,
        )
        websearch_passed = ws_result.passed
        if not ws_result.passed:
            reasons.append(ws_result.reason)

    return LocatorValidationResult(
        evidence_id=locator.evidence_id,
        is_locatable=locator.is_locatable,
        pit_passed=pit_result.passed,
        websearch_passed=websearch_passed,
        reasons=reasons,
    )
