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

import csv
import html
import io
import re
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
    bbox: tuple[float, float, float, float] | None = None
    section: str | None = None
    paragraph_index: int | None = None
    dom_path: str | None = None
    table_id: str | None = None
    row_id: str | None = None
    column_id: str | None = None
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
            or self.bbox is not None
            or bool(self.section)
            or self.paragraph_index is not None
            or bool(self.dom_path)
            or bool(self.table_id)
            or bool(self.row_id)
            or bool(self.column_id)
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
            bbox=evidence.bbox,
            section=evidence.section,
            paragraph_index=evidence.paragraph_index,
            dom_path=evidence.dom_path,
            table_id=evidence.table_id,
            row_id=evidence.row_id,
            column_id=evidence.column_id,
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


class LocatorReplayResult(BaseModel):
    """Result of replaying a locator against stored snapshot content."""

    valid: bool
    reason_code: str
    located_text: str | None = None

    model_config = {"frozen": True}


class LocatorValidator:
    """Replay locators against persisted snapshot content."""

    def __init__(self, snapshot_resolver: SnapshotResolver | object) -> None:
        """Initialize with a callable or object that can resolve snapshots."""
        self._snapshot_resolver = snapshot_resolver

    def validate(
        self,
        *,
        snapshot_id: str,
        snapshot_hash: str,
        locator: CitationLocator,
        expected_text: str,
    ) -> LocatorReplayResult:
        """Validate snapshot hash, locator anchor, and located text."""
        snapshot = self._resolve_snapshot(snapshot_id)
        if snapshot is None:
            return LocatorReplayResult(valid=False, reason_code="snapshot_not_found")
        if getattr(snapshot, "content_hash", None) != snapshot_hash:
            return LocatorReplayResult(
                valid=False,
                reason_code="snapshot_hash_mismatch",
            )
        content = _snapshot_content(snapshot)
        if content is None:
            return LocatorReplayResult(valid=False, reason_code="snapshot_not_found")
        located = _locate_text(content, getattr(snapshot, "content_type", ""), locator)
        if isinstance(located, LocatorReplayResult):
            return located
        if expected_text and expected_text not in located:
            return LocatorReplayResult(
                valid=False,
                reason_code="quote_text_mismatch",
                located_text=located,
            )
        return LocatorReplayResult(
            valid=True,
            reason_code="ok",
            located_text=located,
        )

    def _resolve_snapshot(self, snapshot_id: str) -> object | None:
        """Resolve a snapshot ID via the configured resolver callable or object."""
        resolver = self._snapshot_resolver
        if callable(resolver):
            return resolver(snapshot_id)
        get_snapshot = getattr(resolver, "get_snapshot", None)
        if callable(get_snapshot):
            return get_snapshot(snapshot_id)
        get = getattr(resolver, "get", None)
        if callable(get):
            return get(snapshot_id)
        return None


def _snapshot_content(snapshot: object) -> str | bytes | None:
    """Extract textual or binary content from a snapshot object."""
    for attr in ("content", "text", "raw_content", "body"):
        value = getattr(snapshot, attr, None)
        if value is None and isinstance(snapshot, dict):
            value = snapshot.get(attr)
        if isinstance(value, (bytes, str)):
            return value
    return None


def _locate_text(
    content: str | bytes,
    content_type: str,
    locator: CitationLocator,
) -> str | LocatorReplayResult:
    """Locate text within snapshot content using the locator's structural fields."""
    normalized_content_type = content_type.lower()
    if locator.page is not None and (
        "pdf" in normalized_content_type
        or isinstance(content, bytes)
        and content.startswith(b"%PDF")
    ):
        located = _locate_pdf_page(content, locator.page)
        if isinstance(located, LocatorReplayResult):
            return located
        return _apply_quote_span(located, locator)
    if locator.table_id and locator.row_id:
        located = _locate_table_cell(content, normalized_content_type, locator)
        if located is None:
            return LocatorReplayResult(valid=False, reason_code="table_cell_not_found")
        return _apply_quote_span(located, locator)

    text_content = (
        content.decode("utf-8", errors="replace")
        if isinstance(content, bytes)
        else content
    )
    if locator.dom_path:
        if "html" not in normalized_content_type and "<" not in text_content:
            return LocatorReplayResult(valid=False, reason_code="dom_path_not_found")
        located = _locate_dom_path(text_content, locator.dom_path)
        if located is None:
            return LocatorReplayResult(valid=False, reason_code="dom_path_not_found")
        return _apply_quote_span(located, locator)
    if locator.quote_span:
        return _apply_quote_span(text_content, locator)
    if locator.page is not None:
        return LocatorReplayResult(valid=False, reason_code="pdf_page_not_found")
    return LocatorReplayResult(valid=False, reason_code="locator_missing")


def _locate_pdf_page(
    content: str | bytes,
    page_number: int,
) -> str | LocatorReplayResult:
    """Extract text from a specific PDF page using PyMuPDF."""
    if not isinstance(content, bytes):
        return LocatorReplayResult(valid=False, reason_code="pdf_page_not_found")
    try:
        import fitz  # type: ignore[import-untyped]
    except Exception:  # noqa: BLE001
        return LocatorReplayResult(valid=False, reason_code="pdf_parser_unavailable")
    try:
        document = fitz.open(stream=content, filetype="pdf")
        try:
            page_index = page_number - 1
            if page_index < 0 or page_index >= document.page_count:
                return LocatorReplayResult(
                    valid=False,
                    reason_code="pdf_page_not_found",
                )
            return document.load_page(page_index).get_text("text").strip()
        finally:
            document.close()
    except Exception:  # noqa: BLE001
        return LocatorReplayResult(valid=False, reason_code="pdf_page_not_found")


def _locate_table_cell(
    content: str | bytes,
    content_type: str,
    locator: CitationLocator,
) -> str | None:
    """Locate a table cell value from CSV content using table and row locators."""
    if locator.table_id != "table-1":
        return None
    row_match = re.fullmatch(r"row-(\d+)", locator.row_id or "")
    if row_match is None:
        return None
    row_index = int(row_match.group(1)) - 1
    if row_index < 0:
        return None

    text_content = (
        content.decode("utf-8-sig", errors="replace")
        if isinstance(content, bytes)
        else content
    )
    if "csv" not in content_type and "," not in text_content.partition("\n")[0]:
        return None
    rows = list(csv.DictReader(io.StringIO(text_content)))
    if row_index >= len(rows):
        return None
    row = rows[row_index]
    if locator.column_id:
        value = row.get(locator.column_id)
        return str(value) if value is not None else None
    return "; ".join(f"{key}={value}" for key, value in row.items())


def _locate_dom_path(content: str, dom_path: str) -> str | None:
    """Locate text within HTML content using a DOM path expression."""
    match = re.search(r"/([A-Za-z0-9]+)\[(\d+)\]$", dom_path)
    if match is None:
        return None
    tag = match.group(1)
    index = int(match.group(2)) - 1
    matches = re.findall(
        rf"<{tag}\b[^>]*>(.*?)</{tag}>",
        content,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if index < 0 or index >= len(matches):
        return None
    text = re.sub(r"<[^>]+>", "", matches[index])
    return html.unescape(text).strip()


def _apply_quote_span(
    content: str,
    locator: CitationLocator,
) -> str | LocatorReplayResult:
    """Extract a substring of content using the locator's quote span."""
    if locator.quote_span is None:
        return content
    start, end = locator.quote_span
    if start < 0 or end < start or end > len(content):
        return LocatorReplayResult(
            valid=False,
            reason_code="quote_span_out_of_range",
        )
    return content[start:end]


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
