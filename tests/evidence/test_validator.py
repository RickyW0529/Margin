"""Tests for claim validation, ABSTAINED handling, and audit records (0503 acceptance)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from margin.evidence.models import (
    ClaimType,
    ConflictSeverity,
    Evidence,
    FactOrInference,
    make_claim,
    make_conflict,
)
from margin.evidence.validator import (
    CitationValidator,
    FailReason,
    ValidationAuditor,
    ValidationResult,
    ValidationStatus,
    validate_claims_with_audit,
)
from margin.news.models import SourceLevel
from margin.vector.models import DocType, make_chunk

DECISION_AT = datetime(2026, 6, 18, tzinfo=UTC)
PUB_AT = datetime(2026, 6, 17, tzinfo=UTC)


def _make_evidence(
    source_level=SourceLevel.L1,
    doc_type=DocType.FILING,
    source_url="https://example.com/filing.pdf",
    page=86,
    section="经营现金流",
    available_at=None,
    snapshot_id=None,
):
    """Build a piece of evidence for use in validator tests.

    Args:
        source_level: Source reliability level.
        doc_type: Document type classification.
        source_url: URL or file path for the source.
        page: Page number in the source document.
        section: Section or heading name in the source.
        available_at: Time when the evidence became available; defaults to PUB_AT.
        snapshot_id: Optional snapshot identifier for web sources.

    Returns:
        An Evidence instance built from the generated chunk.
    """
    chunk = make_chunk(
        document_id="doc_001",
        content="经营现金流同比增长32%",
        symbol="000001.SZ",
        source_level=source_level,
        doc_type=doc_type,
        source_url=source_url,
        page=page,
        section=section,
        published_at=PUB_AT,
        available_at=available_at or PUB_AT,
    )
    ev = Evidence.from_chunk(chunk)
    if snapshot_id:
        ev = ev.model_copy(update={"snapshot_id": snapshot_id})
    return ev


def _make_passing_claim(evidence_id, confidence=0.85):
    """Build a fact claim that should pass validation by default.

    Args:
        evidence_id: Identifier of the evidence backing the claim.
        confidence: Initial confidence score for the claim.

    Returns:
        A Claim instance configured as a cash-flow improvement fact.
    """
    return make_claim(
        statement="现金流改善",
        claim_type=ClaimType.CASH_FLOW_IMPROVEMENT,
        fact_or_inference=FactOrInference.FACT,
        evidence_ids=[evidence_id],
        confidence=confidence,
    )


class TestValidateClaimPass:
    """Tests for claims that are expected to pass validation."""

    def test_valid_claim_passes(self):
        """Verify a valid claim with L1 evidence passes and preserves capped confidence."""
        ev = _make_evidence()
        claim = _make_passing_claim(ev.evidence_id)
        validator = CitationValidator()
        result = validator.validate_claim(claim, {ev.evidence_id: ev}, DECISION_AT)

        assert result.status == ValidationStatus.PASS
        assert result.evidences_passed == 1
        assert result.capped_confidence == 0.85

    def test_multiple_evidences_pass(self):
        """Verify a claim backed by multiple valid evidences passes validation."""
        ev1 = _make_evidence()
        ev2 = _make_evidence(source_level=SourceLevel.L2, source_url="https://other.com")
        ev2 = ev2.model_copy(update={"evidence_id": "ev_other"})
        claim = make_claim(
            statement="现金流改善",
            claim_type=ClaimType.CASH_FLOW_IMPROVEMENT,
            evidence_ids=[ev1.evidence_id, ev2.evidence_id],
            confidence=0.9,
        )
        validator = CitationValidator()
        result = validator.validate_claim(
            claim, {ev1.evidence_id: ev1, ev2.evidence_id: ev2}, DECISION_AT
        )
        assert result.status == ValidationStatus.PASS
        assert result.evidences_passed == 2


class TestValidateClaimFail:
    """Tests for claims that are expected to fail validation."""

    def test_no_evidence_fails(self):
        """Verify a claim without evidence fails and is flagged for suppression."""
        claim = make_claim(statement="test", confidence=0.8)
        validator = CitationValidator()
        result = validator.validate_claim(claim, {}, DECISION_AT)
        assert result.status == ValidationStatus.FAIL
        assert result.fail_reason == FailReason.NO_EVIDENCE
        assert result.should_suppress is True

    def test_evidence_not_found_fails(self):
        """Verify a claim referencing missing evidence fails validation."""
        claim = make_claim(statement="test", evidence_ids=["nonexistent"], confidence=0.8)
        validator = CitationValidator()
        result = validator.validate_claim(claim, {}, DECISION_AT)
        assert result.status == ValidationStatus.FAIL
        assert result.fail_reason == FailReason.EVIDENCE_NOT_FOUND

    def test_l5_only_fails(self):
        """Verify a claim backed only by L5 evidence fails with L5_ONLY."""
        ev = _make_evidence(source_level=SourceLevel.L5)
        claim = _make_passing_claim(ev.evidence_id)
        validator = CitationValidator()
        result = validator.validate_claim(claim, {ev.evidence_id: ev}, DECISION_AT)
        assert result.status == ValidationStatus.FAIL
        assert result.fail_reason == FailReason.L5_ONLY

    def test_l4_without_cross_validation_fails(self):
        """Verify a single L4 news claim fails without cross-validation."""
        ev = _make_evidence(
            source_level=SourceLevel.L4,
            doc_type=DocType.NEWS,
            snapshot_id="snp_001",
        )
        claim = _make_passing_claim(ev.evidence_id)
        validator = CitationValidator()
        result = validator.validate_claim(claim, {ev.evidence_id: ev}, DECISION_AT)
        assert result.status == ValidationStatus.FAIL
        assert result.fail_reason == FailReason.L4_NO_CROSS_VALIDATION

    def test_not_locatable_fails(self):
        """Verify a non-locatable claim fails or is abstained."""
        ev = _make_evidence(source_url=None, page=None, section=None)
        claim = _make_passing_claim(ev.evidence_id)
        validator = CitationValidator()
        result = validator.validate_claim(claim, {ev.evidence_id: ev}, DECISION_AT)
        assert result.status in (ValidationStatus.FAIL, ValidationStatus.ABSTAINED)

    def test_lookahead_fails(self):
        """Verify a claim using future evidence fails or is abstained."""
        ev = _make_evidence(available_at=datetime(2026, 6, 20, tzinfo=UTC))
        claim = _make_passing_claim(ev.evidence_id)
        validator = CitationValidator()
        result = validator.validate_claim(claim, {ev.evidence_id: ev}, DECISION_AT)
        assert result.status in (ValidationStatus.FAIL, ValidationStatus.ABSTAINED)


class TestValidateClaimAbstained:
    """Tests for claims that should be abstained rather than fail."""

    def test_insufficient_evidence_abstained(self):
        """Verify a non-locatable cited evidence item fails the claim."""
        ev = _make_evidence(source_url=None, page=None, section=None)
        claim = _make_passing_claim(ev.evidence_id)
        validator = CitationValidator(min_evidence_count=1)
        result = validator.validate_claim(claim, {ev.evidence_id: ev}, DECISION_AT)
        assert result.status == ValidationStatus.FAIL
        assert result.fail_reason == FailReason.NOT_LOCATABLE
        assert result.should_suppress is True

    def test_all_evidence_lookahead_abstained(self):
        """Verify lookahead evidence fails the claim with a specific reason."""
        ev = _make_evidence(available_at=datetime(2026, 6, 20, tzinfo=UTC))
        claim = _make_passing_claim(ev.evidence_id)
        validator = CitationValidator()
        result = validator.validate_claim(claim, {ev.evidence_id: ev}, DECISION_AT)
        assert result.status == ValidationStatus.FAIL
        assert result.fail_reason == FailReason.LOOKAHEAD


class TestConflictHandling:
    """Tests for conflict-based confidence capping."""

    def test_conflict_caps_confidence(self):
        """Verify a medium conflict lowers the claim confidence cap."""
        ev = _make_evidence()
        conflict = make_conflict(
            "clm_1", [ev.evidence_id], "test conflict", ConflictSeverity.MEDIUM
        )
        claim = make_claim(
            statement="现金流改善",
            evidence_ids=[ev.evidence_id],
            confidence=0.9,
            conflicts=[conflict],
        )
        validator = CitationValidator()
        result = validator.validate_claim(claim, {ev.evidence_id: ev}, DECISION_AT)
        assert result.status == ValidationStatus.PASS
        assert result.capped_confidence == 0.5
        assert result.original_confidence == 0.9

    def test_high_conflict_caps_lower(self):
        """Verify a high conflict lowers the claim confidence cap further."""
        ev = _make_evidence()
        conflict = make_conflict(
            "clm_1", [ev.evidence_id], "high conflict", ConflictSeverity.HIGH
        )
        claim = make_claim(
            statement="现金流改善",
            evidence_ids=[ev.evidence_id],
            confidence=0.9,
            conflicts=[conflict],
        )
        validator = CitationValidator()
        result = validator.validate_claim(claim, {ev.evidence_id: ev}, DECISION_AT)
        assert result.status == ValidationStatus.PASS
        assert result.capped_confidence == 0.3


class TestValidateBatch:
    """Tests for validating multiple claims in a single batch."""

    def test_mixed_results(self):
        """Verify validate_batch counts passes and failures across mixed claims."""
        ev_good = _make_evidence()
        ev_l5 = _make_evidence(source_level=SourceLevel.L5)

        claim_pass = _make_passing_claim(ev_good.evidence_id)
        claim_fail = make_claim(
            statement="test", evidence_ids=[ev_l5.evidence_id], confidence=0.8
        )
        claim_no_ev = make_claim(statement="no ev", confidence=0.7)

        validator = CitationValidator()
        report = validator.validate_batch(
            [claim_pass, claim_fail, claim_no_ev],
            {ev_good.evidence_id: ev_good, ev_l5.evidence_id: ev_l5},
            DECISION_AT,
        )

        assert report.total == 3
        assert report.passed == 1
        assert report.failed == 2
        assert report.abstained == 0

    def test_empty_batch(self):
        """Verify validate_batch handles an empty claim list correctly."""
        validator = CitationValidator()
        report = validator.validate_batch([], {}, DECISION_AT)
        assert report.total == 0
        assert report.should_suppress_research is False

    def test_should_suppress_on_abstained(self):
        """Verify an abstained claim triggers research suppression in the report."""
        ev_bad = _make_evidence(source_url=None, page=None, section=None)
        claim = _make_passing_claim(ev_bad.evidence_id, confidence=0.5)
        validator = CitationValidator()
        report = validator.validate_batch(
            [claim], {ev_bad.evidence_id: ev_bad}, DECISION_AT
        )
        assert report.should_suppress_research is True

    def test_should_suppress_on_high_conf_fail(self):
        """Verify a high-confidence failure triggers research suppression."""
        ev_l5 = _make_evidence(source_level=SourceLevel.L5)
        claim = _make_passing_claim(ev_l5.evidence_id, confidence=0.85)
        validator = CitationValidator()
        report = validator.validate_batch(
            [claim], {ev_l5.evidence_id: ev_l5}, DECISION_AT
        )
        assert report.should_suppress_research is True

    def test_no_suppress_when_all_pass(self):
        """Verify no research suppression is triggered when all claims pass."""
        ev = _make_evidence()
        claim = _make_passing_claim(ev.evidence_id, confidence=0.6)
        validator = CitationValidator()
        report = validator.validate_batch(
            [claim], {ev.evidence_id: ev}, DECISION_AT
        )
        assert report.should_suppress_research is False


class TestValidationAuditor:
    """Tests for the validation auditor and its record keeping."""

    def test_log_and_records(self):
        """Verify logging a passing result updates auditor counts and records."""
        ev = _make_evidence()
        claim = _make_passing_claim(ev.evidence_id)
        validator = CitationValidator()
        auditor = ValidationAuditor()

        report = validator.validate_batch(
            [claim], {ev.evidence_id: ev}, DECISION_AT
        )
        for result in report.results:
            auditor.log(result)

        assert len(auditor.records) == 1
        assert auditor.pass_count == 1
        assert auditor.fail_count == 0

    def test_mixed_counts(self):
        """Verify the auditor tallies pass and fail counts correctly."""
        ev_good = _make_evidence()
        ev_l5 = _make_evidence(source_level=SourceLevel.L5)

        claims = [
            _make_passing_claim(ev_good.evidence_id),
            make_claim(statement="t", evidence_ids=[ev_l5.evidence_id], confidence=0.8),
        ]
        validator = CitationValidator()
        auditor = ValidationAuditor()
        report = validator.validate_batch(
            claims, {ev_good.evidence_id: ev_good, ev_l5.evidence_id: ev_l5}, DECISION_AT
        )
        for r in report.results:
            auditor.log(r)

        assert auditor.pass_count == 1
        assert auditor.fail_count == 1
        assert auditor.abstained_count == 0

    def test_audit_record_frozen(self):
        """Verify audit records are immutable after creation."""
        ev = _make_evidence()
        claim = _make_passing_claim(ev.evidence_id)
        validator = CitationValidator()
        result = validator.validate_claim(claim, {ev.evidence_id: ev}, DECISION_AT)

        auditor = ValidationAuditor()
        record = auditor.log(result)
        with pytest.raises(Exception):
            record.status = ValidationStatus.FAIL


class TestValidateClaimsWithAudit:
    """Tests for the combined validation-plus-audit entry point."""

    def test_combined_flow(self):
        """Verify validate_claims_with_audit returns both a report and a populated auditor."""
        ev = _make_evidence()
        claim = _make_passing_claim(ev.evidence_id)

        report, auditor = validate_claims_with_audit(
            [claim], {ev.evidence_id: ev}, DECISION_AT
        )

        assert report.passed == 1
        assert len(auditor.records) == 1

    def test_abstained_suppresses(self):
        """Verify validate_claims_with_audit reports suppression for abstained claims."""
        ev_bad = _make_evidence(source_url=None, page=None, section=None)
        claim = _make_passing_claim(ev_bad.evidence_id)

        report, auditor = validate_claims_with_audit(
            [claim], {ev_bad.evidence_id: ev_bad}, DECISION_AT
        )

        assert report.should_suppress_research is True
        assert auditor.fail_count >= 1


class TestValidationResult:
    """Tests for the ValidationResult data object properties."""

    def test_should_suppress_fail(self):
        """Verify should_suppress is True for a failed validation result."""
        result = ValidationResult(
            claim_id="c1",
            status=ValidationStatus.FAIL,
            reason="test",
            fail_reason=FailReason.NO_EVIDENCE,
        )
        assert result.should_suppress is True

    def test_should_suppress_abstained(self):
        """Verify should_suppress is True for an abstained validation result."""
        result = ValidationResult(
            claim_id="c1",
            status=ValidationStatus.ABSTAINED,
            reason="test",
        )
        assert result.should_suppress is True

    def test_should_not_suppress_pass(self):
        """Verify should_suppress is False for a passed validation result."""
        result = ValidationResult(
            claim_id="c1",
            status=ValidationStatus.PASS,
            reason="ok",
            original_confidence=0.8,
            capped_confidence=0.8,
        )
        assert result.should_suppress is False

    def test_frozen(self):
        """Verify ValidationResult instances are immutable after creation."""
        result = ValidationResult(
            claim_id="c1",
            status=ValidationStatus.PASS,
            reason="ok",
        )
        with pytest.raises(Exception):
            result.reason = "changed"
