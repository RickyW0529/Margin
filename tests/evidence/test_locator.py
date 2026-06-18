"""Tests for citation locator fields and point-in-time checks (0502 acceptance)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from margin.evidence.locator import (
    CitationLocator,
    SourceType,
    build_locator_from_html,
    build_locator_from_pdf,
    build_locator_from_table,
    check_locators_point_in_time,
    check_point_in_time,
    validate_locator,
    verify_websearch_original,
)
from margin.evidence.models import Evidence
from margin.news.models import SourceLevel
from margin.vector.models import DocType, make_chunk


def _make_chunk(
    source_level=SourceLevel.L1,
    doc_type=DocType.FILING,
    content="经营现金流同比增长32%",
    source_url="https://example.com/filing.pdf",
    page=86,
    section="经营现金流",
    paragraph_index=12,
    table_id=None,
    row_id=None,
    quote_span=(120, 188),
):
    """Build a chunk for use in locator tests.

    Args:
        source_level: Source reliability level.
        doc_type: Document type classification.
        content: Text content of the chunk.
        source_url: URL or file path for the source.
        page: Page number in the source document.
        section: Section or heading name in the source.
        paragraph_index: Index of the paragraph within the source.
        table_id: Optional identifier of the source table.
        row_id: Optional identifier of the source table row.
        quote_span: Optional character span of the quoted content.

    Returns:
        A chunk created by the vector model factory.
    """
    return make_chunk(
        document_id="doc_001",
        content=content,
        symbol="000001.SZ",
        source_level=source_level,
        doc_type=doc_type,
        source_url=source_url,
        page=page,
        section=section,
        paragraph_index=paragraph_index,
        table_id=table_id,
        row_id=row_id,
        quote_span=quote_span,
        published_at=datetime(2026, 6, 17, tzinfo=UTC),
        available_at=datetime(2026, 6, 17, tzinfo=UTC),
    )


class TestCitationLocator:
    """Tests for building CitationLocator objects from chunks and evidence."""

    def test_from_evidence(self):
        """Verify CitationLocator.from_evidence copies evidence locator fields."""
        chunk = _make_chunk()
        ev = Evidence.from_chunk(chunk)
        locator = CitationLocator.from_evidence(ev)
        assert locator.evidence_id == ev.evidence_id
        assert locator.source_type == SourceType.FILING_PDF
        assert locator.page == 86
        assert locator.section == "经营现金流"
        assert locator.quote_span == (120, 188)

    def test_from_chunk(self):
        """Verify CitationLocator.from_chunk copies core chunk fields."""
        chunk = _make_chunk()
        locator = CitationLocator.from_chunk(chunk)
        assert locator.document_id == chunk.document_id
        assert locator.source_level == SourceLevel.L1

    def test_is_locatable_with_page(self):
        """Verify a locator is locatable when page and section are present."""
        chunk = _make_chunk()
        locator = CitationLocator.from_chunk(chunk)
        assert locator.is_locatable is True

    def test_is_not_locatable_without_url(self):
        """Verify a locator is not locatable when no source URL is set."""
        chunk = _make_chunk(source_url=None)
        locator = CitationLocator.from_chunk(chunk)
        assert locator.is_locatable is False

    def test_is_not_locatable_without_structural(self):
        """Verify a locator is not locatable without structural fields."""
        chunk = make_chunk(
            document_id="d1",
            content="test",
            source_url="https://example.com",
            source_level=SourceLevel.L1,
        )
        locator = CitationLocator.from_chunk(chunk)
        assert locator.is_locatable is False

    def test_has_snapshot(self):
        """Verify has_snapshot is False when no snapshot ID is set."""
        chunk = _make_chunk()
        ev = Evidence.from_chunk(chunk)
        locator = CitationLocator.from_evidence(ev)
        assert locator.has_snapshot is False

    def test_has_snapshot_true(self):
        """Verify has_snapshot is True when a snapshot ID is present."""
        chunk = _make_chunk()
        ev = Evidence.from_chunk(chunk)
        ev_with_snapshot = ev.model_copy(update={"snapshot_id": "snp_001"})
        locator = CitationLocator.from_evidence(ev_with_snapshot)
        assert locator.has_snapshot is True

    def test_frozen(self):
        """Verify CitationLocator instances are immutable after creation."""
        chunk = _make_chunk()
        locator = CitationLocator.from_chunk(chunk)
        with pytest.raises(Exception):
            locator.page = 999


class TestBuildLocatorFromPDF:
    """Tests for the build_locator_from_pdf helper."""

    def test_pdf_locator(self):
        """Verify build_locator_from_pdf uses explicit page and section values."""
        chunk = _make_chunk(doc_type=DocType.ANNUAL_REPORT)
        locator = build_locator_from_pdf(chunk, page=42, section="财务分析")
        assert locator.source_type == SourceType.FILING_PDF
        assert locator.page == 42
        assert locator.section == "财务分析"
        assert locator.table_id is None

    def test_pdf_locator_defaults_from_chunk(self):
        """Verify build_locator_from_pdf falls back to chunk page, section, and span."""
        chunk = _make_chunk(doc_type=DocType.ANNUAL_REPORT)
        locator = build_locator_from_pdf(chunk)
        assert locator.page == 86
        assert locator.section == "经营现金流"
        assert locator.quote_span == (120, 188)


class TestBuildLocatorFromHTML:
    """Tests for the build_locator_from_html helper."""

    def test_html_locator(self):
        """Verify build_locator_from_html sets paragraph_index and clears non-HTML fields."""
        chunk = _make_chunk(doc_type=DocType.NEWS, page=None, table_id="t1")
        locator = build_locator_from_html(chunk, paragraph_index=5)
        assert locator.source_type == SourceType.WEB_PAGE
        assert locator.paragraph_index == 5
        assert locator.page is None
        assert locator.table_id is None

    def test_html_locator_defaults(self):
        """Verify build_locator_from_html uses the chunk paragraph_index by default."""
        chunk = _make_chunk(doc_type=DocType.NEWS)
        locator = build_locator_from_html(chunk)
        assert locator.paragraph_index == 12
        assert locator.page is None


class TestBuildLocatorFromTable:
    """Tests for the build_locator_from_table helper."""

    def test_table_locator(self):
        """Verify build_locator_from_table captures table_id, row_id, and clears quote_span."""
        chunk = _make_chunk(
            doc_type=DocType.FILING,
            table_id="cash_flow_table",
            row_id="net_operating_cash_flow",
        )
        locator = build_locator_from_table(chunk)
        assert locator.source_type == SourceType.TABLE
        assert locator.table_id == "cash_flow_table"
        assert locator.row_id == "net_operating_cash_flow"
        assert locator.quote_span is None

    def test_table_locator_custom_ids(self):
        """Verify build_locator_from_table accepts explicit table and row IDs."""
        chunk = _make_chunk(doc_type=DocType.FILING)
        locator = build_locator_from_table(chunk, table_id="balance_sheet", row_id="total_assets")
        assert locator.table_id == "balance_sheet"
        assert locator.row_id == "total_assets"


class TestVerifyWebSearchOriginal:
    """Tests for verifying web-search citations are original and locatable."""

    def test_non_web_page_passes(self):
        """Verify non-web-page locators pass web-search verification automatically."""
        chunk = _make_chunk(doc_type=DocType.FILING)
        locator = CitationLocator.from_chunk(chunk)
        result = verify_websearch_original(locator)
        assert result.passed is True

    def test_web_page_without_snapshot_fails(self):
        """Verify web-page locators fail when a snapshot is required but missing."""
        chunk = _make_chunk(doc_type=DocType.NEWS)
        locator = build_locator_from_html(chunk)
        result = verify_websearch_original(locator, require_snapshot=True)
        assert result.passed is False
        assert "snapshot" in result.reason

    def test_web_page_with_snapshot_passes(self):
        """Verify web-page locators pass when a required snapshot is present."""
        chunk = _make_chunk(doc_type=DocType.NEWS)
        locator = build_locator_from_html(chunk)
        locator = locator.model_copy(update={"snapshot_id": "snp_001"})
        result = verify_websearch_original(locator, require_snapshot=True)
        assert result.passed is True

    def test_web_page_without_snapshot_allowed(self):
        """Verify web-page locators pass when snapshot requirement is disabled."""
        chunk = _make_chunk(doc_type=DocType.NEWS)
        locator = build_locator_from_html(chunk)
        result = verify_websearch_original(locator, require_snapshot=False)
        assert result.passed is True

    def test_web_page_no_url_fails(self):
        """Verify web-page locators fail when the source URL is missing."""
        chunk = _make_chunk(doc_type=DocType.NEWS, source_url=None)
        locator = build_locator_from_html(chunk)
        result = verify_websearch_original(locator, require_snapshot=False)
        assert result.passed is False
        assert "source_url" in result.reason

    def test_web_page_not_locatable_fails(self):
        """Verify web-page locators fail when no structural pointer exists."""
        chunk = make_chunk(
            document_id="d1",
            content="snippet only",
            source_url="https://example.com",
            source_level=SourceLevel.L4,
            doc_type=DocType.NEWS,
            page=None,
            section=None,
            paragraph_index=None,
            table_id=None,
            row_id=None,
            quote_span=None,
        )
        locator = build_locator_from_html(chunk)
        result = verify_websearch_original(locator, require_snapshot=False)
        assert result.passed is False
        assert "locatable" in result.reason


class TestPointInTimeCheck:
    """Tests for the single-locator point-in-time check."""

    def test_passes_when_available_before_decision(self):
        """Verify check_point_in_time passes when the source was available before the decision."""
        chunk = _make_chunk()
        locator = CitationLocator.from_chunk(chunk)
        result = check_point_in_time(locator, datetime(2026, 6, 18, tzinfo=UTC))
        assert result.passed is True

    def test_passes_when_equal(self):
        """Verify check_point_in_time passes when availability equals the decision time."""
        chunk = _make_chunk()
        locator = CitationLocator.from_chunk(chunk)
        result = check_point_in_time(locator, datetime(2026, 6, 17, tzinfo=UTC))
        assert result.passed is True

    def test_fails_when_available_after_decision(self):
        """Verify check_point_in_time fails when the source is only available after the decision."""
        chunk = _make_chunk()
        chunk_future = chunk.model_copy(update={
            "available_at": datetime(2026, 6, 20, tzinfo=UTC),
        })
        ev = Evidence.from_chunk(chunk_future)
        locator = CitationLocator.from_evidence(ev)
        result = check_point_in_time(locator, datetime(2026, 6, 18, tzinfo=UTC))
        assert result.passed is False
        assert "lookahead" in result.reason

    def test_naive_decision_at_handled(self):
        """Verify check_point_in_time treats a naive decision datetime as UTC."""
        chunk = _make_chunk()
        locator = CitationLocator.from_chunk(chunk)
        result = check_point_in_time(locator, datetime(2026, 6, 18))
        assert result.passed is True


class TestCheckLocatorsPointInTime:
    """Tests for batch point-in-time checks over multiple locators."""

    def test_batch_mixed(self):
        """Verify check_locators_point_in_time returns separate pass and fail groups."""
        chunk_ok = _make_chunk()
        chunk_future = _make_chunk()
        chunk_future = chunk_future.model_copy(update={
            "available_at": datetime(2026, 6, 20, tzinfo=UTC),
        })

        loc_ok = CitationLocator.from_chunk(chunk_ok)
        loc_future = CitationLocator.from_chunk(chunk_future)

        passed, results = check_locators_point_in_time(
            [loc_ok, loc_future],
            datetime(2026, 6, 18, tzinfo=UTC),
        )
        assert len(passed) == 1
        assert len(results) == 2
        assert results[0].passed is True
        assert results[1].passed is False

    def test_batch_all_pass(self):
        """Verify check_locators_point_in_time includes all valid locators in passed."""
        chunk = _make_chunk()
        locator = CitationLocator.from_chunk(chunk)
        passed, results = check_locators_point_in_time(
            [locator],
            datetime(2026, 6, 18, tzinfo=UTC),
        )
        assert len(passed) == 1


class TestValidateLocator:
    """Tests for the combined locator validation routine."""

    def test_all_pass_filing(self):
        """Verify validate_locator passes for a locatable filing with no lookahead."""
        chunk = _make_chunk(doc_type=DocType.FILING)
        locator = CitationLocator.from_chunk(chunk)
        result = validate_locator(locator, datetime(2026, 6, 18, tzinfo=UTC))
        assert result.all_passed is True
        assert result.is_locatable is True
        assert result.pit_passed is True

    def test_not_locatable_fails(self):
        """Verify validate_locator fails when the locator is not locatable."""
        chunk = make_chunk(
            document_id="d1",
            content="test",
            source_url="https://example.com",
            source_level=SourceLevel.L1,
        )
        locator = CitationLocator.from_chunk(chunk)
        result = validate_locator(locator, datetime(2026, 6, 18, tzinfo=UTC))
        assert result.all_passed is False
        assert "not locatable" in result.reasons[0]

    def test_lookahead_fails(self):
        """Verify validate_locator fails when the source is only available after the decision."""
        chunk = _make_chunk()
        chunk_future = chunk.model_copy(update={
            "available_at": datetime(2026, 6, 20, tzinfo=UTC),
        })
        locator = CitationLocator.from_chunk(chunk_future)
        result = validate_locator(locator, datetime(2026, 6, 18, tzinfo=UTC))
        assert result.all_passed is False
        assert any("lookahead" in r for r in result.reasons)

    def test_websearch_without_snapshot_fails(self):
        """Verify validate_locator fails web-search checks without a snapshot."""
        chunk = _make_chunk(doc_type=DocType.NEWS)
        locator = build_locator_from_html(chunk)
        result = validate_locator(locator, datetime(2026, 6, 18, tzinfo=UTC))
        assert result.all_passed is False
        assert result.websearch_passed is False

    def test_websearch_with_snapshot_passes(self):
        """Verify validate_locator passes web-search checks with a snapshot."""
        chunk = _make_chunk(doc_type=DocType.NEWS)
        locator = build_locator_from_html(chunk)
        locator = locator.model_copy(update={"snapshot_id": "snp_001"})
        result = validate_locator(locator, datetime(2026, 6, 18, tzinfo=UTC))
        assert result.all_passed is True

    def test_skip_websearch_check(self):
        """Verify validate_locator can skip the web-search original-source check."""
        chunk = _make_chunk(doc_type=DocType.NEWS)
        locator = build_locator_from_html(chunk)
        result = validate_locator(
            locator, datetime(2026, 6, 18, tzinfo=UTC), check_websearch=False
        )
        assert result.websearch_passed is None
        assert result.all_passed is True
