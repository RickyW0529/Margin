"""Tests for evidence source levels and the Claim data model (0501 acceptance)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from margin.evidence.models import (
    ClaimType,
    ConflictSeverity,
    Evidence,
    FactOrInference,
    check_l5_restriction,
    detect_conflicts,
    make_claim,
    make_conflict,
)
from margin.news.models import SourceLevel
from margin.vector.models import DocType, make_chunk


def _make_chunk(
    symbol="000001.SZ",
    source_level=SourceLevel.L1,
    doc_type=DocType.FILING,
    content="经营现金流同比增长32%",
    source_url="https://example.com/filing.pdf",
    page=86,
    section="经营现金流",
):
    """Build a chunk for use in evidence tests.

    Args:
        symbol: Stock symbol for the chunk.
        source_level: Source reliability level.
        doc_type: Document type classification.
        content: Text content of the chunk.
        source_url: URL or file path for the source.
        page: Page number in the source document.
        section: Section or heading name in the source.

    Returns:
        A chunk created by the vector model factory.
    """
    return make_chunk(
        document_id="doc_001",
        content=content,
        symbol=symbol,
        source_level=source_level,
        doc_type=doc_type,
        source_url=source_url,
        page=page,
        section=section,
        published_at=datetime(2026, 6, 17, tzinfo=UTC),
        available_at=datetime(2026, 6, 17, tzinfo=UTC),
    )


class TestEvidence:
    """Tests for the Evidence model and Evidence.from_chunk factory."""

    def test_from_chunk_basic(self):
        """Verify Evidence.from_chunk copies core chunk fields to the evidence object."""
        chunk = _make_chunk()
        ev = Evidence.from_chunk(chunk)
        assert ev.chunk_id == chunk.chunk_id
        assert ev.document_id == chunk.document_id
        assert ev.source_level == SourceLevel.L1
        assert ev.page == 86
        assert ev.section == "经营现金流"
        assert ev.content_hash == chunk.content_hash

    def test_from_chunk_infers_source_type_filing(self):
        """Verify that filing chunks produce source_type 'filing_pdf'."""
        chunk = _make_chunk(doc_type=DocType.FILING)
        ev = Evidence.from_chunk(chunk)
        assert ev.source_type == "filing_pdf"

    def test_from_chunk_infers_source_type_news(self):
        """Verify that news chunks produce source_type 'web_page'."""
        chunk = _make_chunk(doc_type=DocType.NEWS)
        ev = Evidence.from_chunk(chunk)
        assert ev.source_type == "web_page"

    def test_from_chunk_infers_source_type_user_note(self):
        """Verify that user note chunks produce source_type 'user_file'."""
        chunk = _make_chunk(doc_type=DocType.USER_NOTE)
        ev = Evidence.from_chunk(chunk)
        assert ev.source_type == "user_file"

    def test_can_change_research_state_l1(self):
        """Verify L1 evidence is allowed to change the research state."""
        chunk = _make_chunk(source_level=SourceLevel.L1)
        ev = Evidence.from_chunk(chunk)
        assert ev.can_change_research_state is True

    def test_can_change_research_state_l4(self):
        """Verify L4 evidence is not allowed to change the research state."""
        chunk = _make_chunk(source_level=SourceLevel.L4)
        ev = Evidence.from_chunk(chunk)
        assert ev.can_change_research_state is False

    def test_can_change_research_state_l5(self):
        """Verify L5 evidence is not allowed to change the research state."""
        chunk = _make_chunk(source_level=SourceLevel.L5)
        ev = Evidence.from_chunk(chunk)
        assert ev.can_change_research_state is False

    def test_is_locatable_with_page(self):
        """Verify evidence is locatable when page and section are present."""
        chunk = _make_chunk(page=86, section="现金流")
        ev = Evidence.from_chunk(chunk)
        assert ev.is_locatable is True

    def test_is_not_locatable_without_url(self):
        """Verify evidence is not locatable when no source URL is set."""
        chunk = _make_chunk(source_url=None)
        ev = Evidence.from_chunk(chunk)
        assert ev.is_locatable is False

    def test_is_not_locatable_without_structural(self):
        """Verify evidence is not locatable without structural fields."""
        chunk = make_chunk(
            document_id="doc_1",
            content="test",
            source_url="https://example.com",
            source_level=SourceLevel.L1,
            page=None,
            section=None,
            paragraph_index=None,
            table_id=None,
            row_id=None,
            quote_span=None,
        )
        ev = Evidence.from_chunk(chunk)
        assert ev.is_locatable is False

    def test_frozen(self):
        """Verify Evidence instances are immutable after creation."""
        chunk = _make_chunk()
        ev = Evidence.from_chunk(chunk)
        with pytest.raises(Exception):
            ev.content = "changed"


class TestClaim:
    """Tests for Claim creation, validation, and property helpers."""

    def test_make_claim_basic(self):
        """Verify make_claim assigns a claim ID and stores all given fields."""
        claim = make_claim(
            statement="现金流改善",
            claim_type=ClaimType.CASH_FLOW_IMPROVEMENT,
            fact_or_inference=FactOrInference.FACT,
            evidence_ids=["ev_1", "ev_2"],
            confidence=0.87,
        )
        assert claim.claim_id.startswith("clm_")
        assert claim.claim_type == ClaimType.CASH_FLOW_IMPROVEMENT
        assert claim.fact_or_inference == FactOrInference.FACT
        assert len(claim.evidence_ids) == 2
        assert claim.confidence == 0.87

    def test_confidence_validation(self):
        """Verify confidence values outside [0, 1] raise ValueError."""
        with pytest.raises(ValueError, match="confidence"):
            make_claim(statement="test", confidence=1.5)
        with pytest.raises(ValueError, match="confidence"):
            make_claim(statement="test", confidence=-0.1)

    def test_has_evidence(self):
        """Verify has_evidence is True when evidence IDs are present."""
        claim = make_claim(statement="test", evidence_ids=["ev_1"])
        assert claim.has_evidence is True

    def test_no_evidence(self):
        """Verify has_evidence is False when no evidence IDs are present."""
        claim = make_claim(statement="test")
        assert claim.has_evidence is False

    def test_is_fact(self):
        """Verify is_fact and is_inference reflect a fact claim."""
        claim = make_claim(statement="test", fact_or_inference=FactOrInference.FACT)
        assert claim.is_fact is True
        assert claim.is_inference is False

    def test_is_inference(self):
        """Verify is_fact and is_inference reflect an inference claim."""
        claim = make_claim(statement="test", fact_or_inference=FactOrInference.INFERENCE)
        assert claim.is_inference is True
        assert claim.is_fact is False

    def test_frozen(self):
        """Verify Claim instances are immutable after creation."""
        claim = make_claim(statement="test")
        with pytest.raises(Exception):
            claim.statement = "changed"

    def test_conflict_confidence_cap_no_conflict(self):
        """Verify the confidence cap equals confidence when there is no conflict."""
        claim = make_claim(statement="test", confidence=0.9)
        assert claim.conflict_confidence_cap == 0.9

    def test_conflict_confidence_cap_medium(self):
        """Verify a medium conflict caps confidence at the expected level."""
        conflict = make_conflict("clm_1", ["ev_1"], severity=ConflictSeverity.MEDIUM)
        claim = make_claim(statement="test", confidence=0.9, conflicts=[conflict])
        assert claim.conflict_confidence_cap == 0.5

    def test_conflict_confidence_cap_high(self):
        """Verify a high conflict caps confidence at the expected level."""
        conflict = make_conflict("clm_1", ["ev_1"], severity=ConflictSeverity.HIGH)
        claim = make_claim(statement="test", confidence=0.9, conflicts=[conflict])
        assert claim.conflict_confidence_cap == 0.3

    def test_conflict_confidence_cap_already_low(self):
        """Verify the confidence cap does not raise confidence."""
        conflict = make_conflict("clm_1", ["ev_1"], severity=ConflictSeverity.HIGH)
        claim = make_claim(statement="test", confidence=0.2, conflicts=[conflict])
        assert claim.conflict_confidence_cap == 0.2


class TestConflictRecord:
    """Tests for the conflict record factory and its frozen behavior."""

    def test_make_conflict(self):
        """Verify make_conflict creates a conflict with the expected fields."""
        c = make_conflict("clm_1", ["ev_1", "ev_2"], "desc", ConflictSeverity.HIGH)
        assert c.conflict_id.startswith("cfl_")
        assert c.claim_id == "clm_1"
        assert len(c.conflicting_evidence_ids) == 2
        assert c.severity == ConflictSeverity.HIGH

    def test_frozen(self):
        """Verify ConflictRecord instances are immutable after creation."""
        c = make_conflict("clm_1", ["ev_1"])
        with pytest.raises(Exception):
            c.description = "changed"


class TestDetectConflicts:
    """Tests for the detect_conflicts helper across claim sets."""

    def test_no_conflicts(self):
        """Verify detect_conflicts returns empty when claims do not conflict."""
        chunk = _make_chunk()
        ev = Evidence.from_chunk(chunk)
        claim = make_claim(
            statement="现金流改善",
            claim_type=ClaimType.CASH_FLOW_IMPROVEMENT,
            evidence_ids=[ev.evidence_id],
        )
        conflicts = detect_conflicts([claim], {ev.evidence_id: ev})
        assert len(conflicts) == 0

    def test_contradictory_claims(self):
        """Verify detect_conflicts flags contradictory claims of the same type."""
        chunk = _make_chunk()
        ev = Evidence.from_chunk(chunk)
        claim_a = make_claim(
            statement="现金流改善",
            claim_type=ClaimType.CASH_FLOW_IMPROVEMENT,
            evidence_ids=[ev.evidence_id],
        )
        claim_b = make_claim(
            statement="现金流恶化",
            claim_type=ClaimType.CASH_FLOW_IMPROVEMENT,
            evidence_ids=[ev.evidence_id],
        )
        conflicts = detect_conflicts([claim_a, claim_b], {ev.evidence_id: ev})
        assert claim_a.claim_id in conflicts
        assert len(conflicts[claim_a.claim_id]) >= 1

    def test_level_conflict_l5_vs_l1(self):
        """Verify mixing L5 and L1 evidence on one claim raises a high-severity conflict."""
        chunk_l1 = _make_chunk(source_level=SourceLevel.L1)
        chunk_l5 = _make_chunk(source_level=SourceLevel.L5)
        ev_l1 = Evidence.from_chunk(chunk_l1)
        ev_l5 = Evidence.from_chunk(chunk_l5)

        claim = make_claim(
            statement="现金流改善",
            evidence_ids=[ev_l1.evidence_id, ev_l5.evidence_id],
        )
        conflicts = detect_conflicts([claim], {
            ev_l1.evidence_id: ev_l1,
            ev_l5.evidence_id: ev_l5,
        })
        assert claim.claim_id in conflicts
        assert any(c.severity == ConflictSeverity.HIGH for c in conflicts[claim.claim_id])

    def test_different_claim_types_no_conflict(self):
        """Verify contradictory statements of different claim types do not conflict."""
        chunk = _make_chunk()
        ev = Evidence.from_chunk(chunk)
        claim_a = make_claim(
            statement="现金流改善",
            claim_type=ClaimType.CASH_FLOW_IMPROVEMENT,
            evidence_ids=[ev.evidence_id],
        )
        claim_b = make_claim(
            statement="现金流恶化",
            claim_type=ClaimType.RISK_EVENT,
            evidence_ids=[ev.evidence_id],
        )
        conflicts = detect_conflicts([claim_a, claim_b], {ev.evidence_id: ev})
        assert len(conflicts) == 0


class TestL5Restriction:
    """Tests for the L5 evidence restriction helper."""

    def test_only_l5_fails(self):
        """Verify a claim supported only by L5 evidence fails the restriction."""
        chunk = _make_chunk(source_level=SourceLevel.L5)
        ev = Evidence.from_chunk(chunk)
        claim = make_claim(
            statement="test",
            evidence_ids=[ev.evidence_id],
        )
        assert check_l5_restriction(claim, {ev.evidence_id: ev}) is False

    def test_l5_plus_l1_passes(self):
        """Verify a claim with both L5 and L1 evidence passes the restriction."""
        chunk_l5 = _make_chunk(source_level=SourceLevel.L5)
        chunk_l1 = _make_chunk(source_level=SourceLevel.L1)
        ev_l5 = Evidence.from_chunk(chunk_l5)
        ev_l1 = Evidence.from_chunk(chunk_l1)
        claim = make_claim(
            statement="test",
            evidence_ids=[ev_l5.evidence_id, ev_l1.evidence_id],
        )
        assert check_l5_restriction(claim, {
            ev_l5.evidence_id: ev_l5,
            ev_l1.evidence_id: ev_l1,
        }) is True

    def test_no_evidence_fails(self):
        """Verify a claim with no evidence fails the restriction."""
        claim = make_claim(statement="test")
        assert check_l5_restriction(claim, {}) is False

    def test_l4_passes(self):
        """Verify a claim supported only by L4 evidence passes the restriction."""
        chunk = _make_chunk(source_level=SourceLevel.L4)
        ev = Evidence.from_chunk(chunk)
        claim = make_claim(
            statement="test",
            evidence_ids=[ev.evidence_id],
        )
        assert check_l5_restriction(claim, {ev.evidence_id: ev}) is True
