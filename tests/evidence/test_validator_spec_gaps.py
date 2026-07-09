"""Regression tests for RAG evidence spec gaps."""

from __future__ import annotations

from datetime import UTC, datetime

from margin.evidence.locator import CitationLocator, SourceType, validate_locator
from margin.evidence.models import ClaimType, Evidence, FactOrInference, make_claim
from margin.evidence.validator import CitationValidator, FailReason, ValidationStatus
from margin.news.models import RawSnapshot, SourceLevel, compute_content_hash
from margin.vector.models import DocType, make_chunk

DECISION_AT = datetime(2026, 6, 18, tzinfo=UTC)
PUB_AT = datetime(2026, 6, 17, tzinfo=UTC)


def _evidence(
    *,
    evidence_id: str,
    statement_text: str = "经营现金流同比增长32%",
    source_level: SourceLevel = SourceLevel.L1,
    doc_type: DocType = DocType.FILING,
    source_url: str | None = "https://example.com/filing.pdf",
    page: int | None = 86,
    section: str | None = "经营现金流",
    paragraph_index: int | None = None,
    snapshot_id: str | None = None,
    snapshot_hash: str | None = None,
) -> Evidence:
    """Build an evidence fixture with deterministic IDs and locators.

    Args:
        evidence_id: str: .
        statement_text: str: .
        source_level: SourceLevel: .
        doc_type: DocType: .
        source_url: str | None: .
        page: int | None: .
        section: str | None: .
        paragraph_index: int | None: .
        snapshot_id: str | None: .
        snapshot_hash: str | None: .

    Returns:
        Evidence: .
    """
    chunk = make_chunk(
        document_id=f"doc_{evidence_id}",
        content=statement_text,
        symbol="000001.SZ",
        source_level=source_level,
        doc_type=doc_type,
        source_url=source_url,
        page=page,
        section=section,
        paragraph_index=paragraph_index,
        published_at=PUB_AT,
        available_at=PUB_AT,
    )
    return Evidence.from_chunk(chunk).model_copy(
        update={
            "evidence_id": evidence_id,
            "snapshot_id": snapshot_id,
            "snapshot_hash": snapshot_hash,
        }
    )


def _claim(statement: str, evidence: Evidence, confidence: float = 0.9):
    """Build a cash-flow claim referencing one evidence item.

    Args:
        statement: str: .
        evidence: Evidence: .
        confidence: float: .

    Returns:
        Any: .
    """
    return make_claim(
        statement=statement,
        claim_type=ClaimType.CASH_FLOW_IMPROVEMENT,
        fact_or_inference=FactOrInference.FACT,
        evidence_ids=[evidence.evidence_id],
        confidence=confidence,
        locator=CitationLocator.from_evidence(evidence).model_dump(mode="json"),
    )


def test_batch_validation_detects_cross_claim_conflicts_and_suppresses_high_confidence():
    """Contradictory claims in the same validation batch must be conflict-capped.

    Returns:
        Any: .
    """
    positive_evidence = _evidence(evidence_id="ev_positive")
    negative_evidence = _evidence(
        evidence_id="ev_negative",
        statement_text="经营现金流同比下降20%",
    )
    positive = _claim("经营现金流改善", positive_evidence)
    negative = _claim("经营现金流恶化", negative_evidence)

    report = CitationValidator().validate_batch(
        [positive, negative],
        {
            positive_evidence.evidence_id: positive_evidence,
            negative_evidence.evidence_id: negative_evidence,
        },
        DECISION_AT,
    )

    assert report.total == 2
    assert all(result.conflicts_found >= 1 for result in report.results)
    assert all(result.capped_confidence < result.original_confidence for result in report.results)
    assert all(result.requires_counter_review for result in report.results)
    assert report.should_suppress_research is True


def test_invalid_locator_fails_claim_with_specific_reason():
    """A cited evidence item without original-source location must fail the claim.

    Returns:
        Any: .
    """
    evidence = _evidence(evidence_id="ev_no_locator", source_url=None, page=None, section=None)
    claim = _claim("经营现金流改善", evidence)

    result = CitationValidator().validate_claim(
        claim,
        {evidence.evidence_id: evidence},
        DECISION_AT,
    )

    assert result.status == ValidationStatus.FAIL
    assert result.fail_reason == FailReason.NOT_LOCATABLE
    assert result.should_suppress is True


def test_websearch_snapshot_resolver_rejects_hash_mismatch_and_accepts_matching_snapshot():
    """WebSearch citations must resolve to a stored original snapshot with matching metadata.

    Returns:
        Any: .
    """
    snapshot_hash = compute_content_hash("<html>公告原文</html>")
    locator = CitationLocator(
        evidence_id="ev_web",
        document_id="doc_web",
        source_type=SourceType.WEB_PAGE,
        source_url="https://example.com/article",
        source_level=SourceLevel.L4,
        content_hash=compute_content_hash("公告摘要"),
        snapshot_id="snp_web",
        snapshot_hash=snapshot_hash,
        paragraph_index=2,
        published_at=PUB_AT,
        available_at=PUB_AT,
        retrieved_at=PUB_AT,
    )
    wrong_snapshot = RawSnapshot(
        snapshot_id="snp_web",
        source_url="https://example.com/article",
        content_hash=compute_content_hash("<html>其他内容</html>"),
        content_type="html",
        raw_size=20,
        downloaded_at=PUB_AT,
        http_status=200,
    )
    right_snapshot = wrong_snapshot.model_copy(update={"content_hash": snapshot_hash})

    rejected = validate_locator(
        locator,
        DECISION_AT,
        snapshot_resolver=lambda snapshot_id: wrong_snapshot if snapshot_id == "snp_web" else None,
    )
    accepted = validate_locator(
        locator,
        DECISION_AT,
        snapshot_resolver=lambda snapshot_id: right_snapshot if snapshot_id == "snp_web" else None,
    )

    assert rejected.all_passed is False
    assert rejected.websearch_passed is False
    assert accepted.all_passed is True
