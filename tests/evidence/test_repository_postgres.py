"""PostgreSQL persistence tests for RAG evidence claims and audits."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from margin.evidence.db_models import (
    EvidenceClaimRow,
    EvidenceRecordRow,
    EvidenceValidationAuditRow,
    ResearchEvidenceRow,
)
from margin.evidence.locator import CitationLocator
from margin.evidence.models import ClaimType, Evidence, FactOrInference, make_claim
from margin.evidence.repository import EvidenceRepository
from margin.evidence.validator import CitationValidator, ValidationAuditor
from margin.news.models import SourceLevel
from margin.storage.base import Base
from margin.storage.database import DatabaseSettings, create_database_engine, create_session_factory
from margin.vector.models import DocType, make_chunk

DECISION_AT = datetime(2026, 6, 18, tzinfo=UTC)
PUB_AT = datetime(2026, 6, 17, tzinfo=UTC)


@pytest.fixture
def evidence_repository(database_url):
    """Yield a clean evidence repository backed by PostgreSQL.

    Args:
        database_url: Any: .

    Yields:
        Any: .
    """
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    with session_factory.begin() as session:
        for row in (
            EvidenceValidationAuditRow,
            ResearchEvidenceRow,
            EvidenceClaimRow,
            EvidenceRecordRow,
        ):
            session.query(row).delete()
    yield EvidenceRepository(session_factory)
    Base.metadata.drop_all(engine)
    engine.dispose()


def _evidence(evidence_id: str = "ev_persisted") -> Evidence:
    """Build a deterministic evidence fixture.

    Args:
        evidence_id: str: .

    Returns:
        Evidence: .
    """
    chunk = make_chunk(
        document_id="doc_001",
        content="经营现金流同比增长32%",
        symbol="000001.SZ",
        source_level=SourceLevel.L1,
        doc_type=DocType.FILING,
        source_url="https://example.com/filing.pdf",
        page=86,
        section="经营现金流",
        published_at=PUB_AT,
        available_at=PUB_AT,
    )
    return Evidence.from_chunk(chunk).model_copy(update={"evidence_id": evidence_id})


def _claim(evidence: Evidence):
    """Build a deterministic claim fixture with an embedded primary locator.

    Args:
        evidence: Evidence: .

    Returns:
        Any: .
    """
    locator = CitationLocator.from_evidence(evidence)
    return make_claim(
        statement="经营现金流质量改善",
        claim_type=ClaimType.CASH_FLOW_IMPROVEMENT,
        fact_or_inference=FactOrInference.FACT,
        evidence_ids=[evidence.evidence_id],
        confidence=0.87,
        locator=locator.model_dump(mode="json"),
        symbol="000001.SZ",
        effective_at=DECISION_AT,
    )


def test_repository_persists_evidence_claim_audit_and_research_link(evidence_repository):
    """Evidence, claims, validation audits, and research links round-trip.

    Args:
        evidence_repository: Any: .

    Returns:
        Any: .
    """
    evidence = _evidence()
    claim = _claim(evidence)

    evidence_repository.add_evidence(evidence)
    evidence_repository.add_claim(claim)

    validator = CitationValidator()
    result = validator.validate_claim(claim, {evidence.evidence_id: evidence}, DECISION_AT)
    audit = ValidationAuditor().log(result)
    evidence_repository.add_validation_audit(audit)
    evidence_repository.link_research_evidence(
        research_item_id="ri_001",
        claim_id=claim.claim_id,
        evidence_id=evidence.evidence_id,
        role="supporting",
        rank=1,
    )

    assert evidence_repository.get_evidence(evidence.evidence_id) == evidence
    stored_claim = evidence_repository.get_claim(claim.claim_id)
    assert stored_claim == claim
    assert stored_claim.locator["evidence_id"] == evidence.evidence_id
    assert evidence_repository.list_validation_audits(claim.claim_id) == [audit]
    links = evidence_repository.list_research_evidence("ri_001")
    assert [(link.claim_id, link.evidence_id, link.role, link.rank) for link in links] == [
        (claim.claim_id, evidence.evidence_id, "supporting", 1)
    ]


def test_repository_rejects_mutating_existing_claim(evidence_repository):
    """Persisted claims are append-only and cannot be mutated by reinsert.

    Args:
        evidence_repository: Any: .

    Returns:
        Any: .
    """
    evidence = _evidence()
    claim = _claim(evidence)
    evidence_repository.add_evidence(evidence)
    evidence_repository.add_claim(claim)

    changed = claim.model_copy(update={"statement": "经营现金流质量恶化"})

    with pytest.raises(ValueError, match="immutable"):
        evidence_repository.add_claim(changed)
