"""v0.2 locator replay tests against persisted snapshot content.

Verifies that :class:`LocatorValidator` replays HTML, PDF, and CSV locators
against in-memory snapshots, detects hash mismatches and out-of-range quote
spans, and that :class:`CitationValidator` fails claims whose replayed quote
does not match the stored snapshot.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from margin.evidence.locator import CitationLocator, LocatorValidator, SourceType
from margin.evidence.models import Evidence, make_claim
from margin.evidence.validator import CitationValidator, ValidationStatus
from margin.news.models import SourceLevel
from margin.vector.models import DocType, SourceLocator, make_chunk


def test_html_locator_replays_against_snapshot(snapshot_resolver) -> None:
    """Test that an HTML locator replays correctly against a stored snapshot.

    Args:
        snapshot_resolver: In-memory snapshot resolver fixture.
    """
    snapshot_resolver.add_html(
        "snap-1",
        "<h1>公告</h1><p>收入增长 20%。</p>",
        "sha256:html",
    )
    validator = LocatorValidator(snapshot_resolver)

    result = validator.validate(
        snapshot_id="snap-1",
        snapshot_hash="sha256:html",
        locator=CitationLocator(
            evidence_id="ev-1",
            document_id="doc-1",
            source_type=SourceType.WEB_PAGE,
            source_url="https://example.com/news",
            source_level=SourceLevel.L1,
            content_hash="sha256:chunk",
            available_at=datetime(2026, 6, 22, tzinfo=UTC),
            dom_path="/html/body/p[1]",
            quote_span=(0, 8),
        ),
        expected_text="收入增长 20%",
    )

    assert result.valid is True
    assert result.located_text == "收入增长 20%"


def test_pdf_page_locator_replays_against_snapshot(snapshot_resolver) -> None:
    """Test that a PDF page locator replays correctly against a stored snapshot.

    Args:
        snapshot_resolver: In-memory snapshot resolver fixture.
    """
    fitz = pytest.importorskip("fitz")
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Operating cash flow improved.")
    snapshot_resolver.add_binary(
        "snap-pdf",
        document.tobytes(),
        "sha256:pdf",
        content_type="application/pdf",
    )

    result = LocatorValidator(snapshot_resolver).validate(
        snapshot_id="snap-pdf",
        snapshot_hash="sha256:pdf",
        locator=CitationLocator(
            evidence_id="ev-pdf",
            document_id="doc-pdf",
            source_type=SourceType.FILING_PDF,
            source_url="https://example.com/filing.pdf",
            source_level=SourceLevel.L1,
            content_hash="sha256:chunk",
            available_at=datetime(2026, 6, 22, tzinfo=UTC),
            page=1,
        ),
        expected_text="Operating cash flow improved.",
    )

    assert result.valid is True
    assert result.located_text is not None
    assert "Operating cash flow improved." in result.located_text


def test_csv_table_cell_locator_replays_against_snapshot(snapshot_resolver) -> None:
    """Test that a CSV table-cell locator replays correctly against a stored snapshot.

    Args:
        snapshot_resolver: In-memory snapshot resolver fixture.
    """
    snapshot_resolver.add_text(
        "snap-csv",
        "period,revenue\n2025,100\n",
        "sha256:csv",
        content_type="text/csv",
    )

    result = LocatorValidator(snapshot_resolver).validate(
        snapshot_id="snap-csv",
        snapshot_hash="sha256:csv",
        locator=CitationLocator(
            evidence_id="ev-csv",
            document_id="doc-csv",
            source_type=SourceType.TABLE,
            source_url="https://example.com/financials.csv",
            source_level=SourceLevel.L2,
            content_hash="sha256:chunk",
            available_at=datetime(2026, 6, 22, tzinfo=UTC),
            table_id="table-1",
            row_id="row-1",
            column_id="revenue",
        ),
        expected_text="100",
    )

    assert result.valid is True
    assert result.located_text == "100"


def test_evidence_preserves_structured_chunk_locator_fields() -> None:
    """Test that evidence preserves structured chunk locator fields.

    Verifies that ``bbox``, ``dom_path``, and ``column_id`` from a
    :class:`SourceLocator` are carried through to the evidence and the
    citation locator.
    """
    chunk = make_chunk(
        document_id="doc-structured",
        content="收入增长 20%",
        symbol="000001.SZ",
        source_level=SourceLevel.L1,
        doc_type=DocType.NEWS,
        source_url="https://example.com/news",
        locator=SourceLocator(
            bbox=(1.0, 2.0, 3.0, 4.0),
            dom_path="/html/body/p[1]",
            column_id="revenue",
        ),
    )

    evidence = Evidence.from_chunk(chunk)
    locator = CitationLocator.from_evidence(evidence)

    assert evidence.bbox == (1.0, 2.0, 3.0, 4.0)
    assert evidence.dom_path == "/html/body/p[1]"
    assert evidence.column_id == "revenue"
    assert locator.bbox == evidence.bbox
    assert locator.dom_path == evidence.dom_path
    assert locator.column_id == evidence.column_id


def test_snapshot_hash_mismatch_fails(snapshot_resolver) -> None:
    """Test that a snapshot hash mismatch causes replay validation to fail.

    Args:
        snapshot_resolver: In-memory snapshot resolver fixture.
    """
    snapshot_resolver.add_text("snap-1", "收入增长 20%。", "sha256:actual")
    validator = LocatorValidator(snapshot_resolver)

    result = validator.validate(
        snapshot_id="snap-1",
        snapshot_hash="sha256:stale",
        locator=CitationLocator(
            evidence_id="ev-1",
            document_id="doc-1",
            source_type=SourceType.WEB_PAGE,
            source_url="https://example.com/news",
            source_level=SourceLevel.L1,
            content_hash="sha256:chunk",
            available_at=datetime(2026, 6, 22, tzinfo=UTC),
            quote_span=(0, 8),
        ),
        expected_text="收入增长 20%",
    )

    assert result.valid is False
    assert result.reason_code == "snapshot_hash_mismatch"


def test_quote_span_out_of_range_fails(snapshot_resolver) -> None:
    """Test that an out-of-range quote span causes replay validation to fail.

    Args:
        snapshot_resolver: In-memory snapshot resolver fixture.
    """
    snapshot_resolver.add_text("snap-1", "短文本", "sha256:short")
    validator = LocatorValidator(snapshot_resolver)

    result = validator.validate(
        snapshot_id="snap-1",
        snapshot_hash="sha256:short",
        locator=CitationLocator(
            evidence_id="ev-1",
            document_id="doc-1",
            source_type=SourceType.WEB_PAGE,
            source_url="https://example.com/news",
            source_level=SourceLevel.L1,
            content_hash="sha256:chunk",
            available_at=datetime(2026, 6, 22, tzinfo=UTC),
            quote_span=(0, 99),
        ),
        expected_text="收入增长",
    )

    assert result.valid is False
    assert result.reason_code == "quote_span_out_of_range"


def test_citation_validator_fails_when_replayed_quote_mismatches_snapshot(
    snapshot_resolver,
) -> None:
    """Test that the citation validator fails when a replayed quote mismatches the snapshot.

    Args:
        snapshot_resolver: In-memory snapshot resolver fixture.
    """
    snapshot_resolver.add_text("snap-1", "利润下降 10%。", "sha256:snapshot")
    evidence = Evidence(
        evidence_id="ev-1",
        chunk_id="chk-1",
        document_id="doc-1",
        source_type="web_page",
        source_url="https://example.com/news",
        source_level=SourceLevel.L1,
        content_hash="sha256:chunk",
        content="收入增长 20%",
        symbol="000001.SZ",
        available_at=datetime(2026, 6, 22, tzinfo=UTC),
        published_at=datetime(2026, 6, 22, tzinfo=UTC),
        quote_span=(0, 7),
        snapshot_id="snap-1",
        snapshot_hash="sha256:snapshot",
    )
    claim = make_claim(
        statement="收入增长",
        evidence_ids=["ev-1"],
        confidence=0.8,
        symbol="000001.SZ",
    )

    result = CitationValidator(snapshot_resolver=snapshot_resolver).validate_claim(
        claim,
        {"ev-1": evidence},
        datetime(2026, 6, 22, tzinfo=UTC),
    )

    assert result.status == ValidationStatus.FAIL
    assert "quote_text_mismatch" in result.reason


class InMemorySnapshotResolver:
    """In-memory snapshot resolver for locator replay tests.

    Stores snapshots keyed by ID and returns them as ``SimpleNamespace``
    objects mimicking the real snapshot resolver interface.
    """

    def __init__(self) -> None:
        """Initialize the resolver with an empty snapshot store."""
        self.snapshots = {}

    def add_html(self, snapshot_id: str, content: str, content_hash: str) -> None:
        """Store an HTML snapshot with the given ID and hash."""
        self.snapshots[snapshot_id] = SimpleNamespace(
            snapshot_id=snapshot_id,
            source_url="https://example.com/news",
            content_hash=content_hash,
            content_type="html",
            content=content,
            http_status=200,
        )

    def add_text(
        self,
        snapshot_id: str,
        content: str,
        content_hash: str,
        *,
        content_type: str = "text",
    ) -> None:
        """Store a text snapshot with the given ID, hash, and content type."""
        self.snapshots[snapshot_id] = SimpleNamespace(
            snapshot_id=snapshot_id,
            source_url="https://example.com/news",
            content_hash=content_hash,
            content_type=content_type,
            content=content,
            http_status=200,
        )

    def add_binary(
        self,
        snapshot_id: str,
        content: bytes,
        content_hash: str,
        *,
        content_type: str,
    ) -> None:
        """Store a binary snapshot with the given ID, hash, and content type."""
        self.snapshots[snapshot_id] = SimpleNamespace(
            snapshot_id=snapshot_id,
            source_url="https://example.com/filing.pdf",
            content_hash=content_hash,
            content_type=content_type,
            content=content,
            http_status=200,
        )

    def __call__(self, snapshot_id: str):
        """Return the snapshot stored under the given ID, or ``None``."""
        return self.snapshots.get(snapshot_id)


@pytest.fixture
def snapshot_resolver() -> InMemorySnapshotResolver:
    """Provide a fresh in-memory snapshot resolver for each test."""
    return InMemorySnapshotResolver()
