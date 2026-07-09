"""v0.2 claim validation policy tests.

Verifies that the v0.2 citation policy abstains critical claims backed only by
L4 evidence without cross-validation, instead of passing them.
"""

from __future__ import annotations

from datetime import UTC, datetime

from margin.evidence.models import ClaimType, Evidence, FactOrInference, make_claim
from margin.evidence.validator import CitationValidator, FailReason, ValidationStatus
from margin.news.models import SourceLevel
from margin.vector.models import DocType, make_chunk

DECISION_AT = datetime(2026, 6, 22, tzinfo=UTC)


def test_critical_claim_with_only_l4_evidence_can_abstain_under_v02_policy() -> None:
    """Test that a critical claim with only L4 evidence can abstain under v0.2 policy.
    Returns:.

    Returns:
        None: .
    """
    evidence = _evidence("ev-1", source_level=SourceLevel.L4)
    claim = make_claim(
        statement="存在重大风险事件",
        claim_type=ClaimType.RISK_EVENT,
        fact_or_inference=FactOrInference.FACT,
        evidence_ids=[evidence.evidence_id],
        confidence=0.82,
        symbol="000001.SZ",
        effective_at=DECISION_AT,
    )

    result = CitationValidator(l4_only_status=ValidationStatus.ABSTAINED).validate_claim(
        claim,
        {evidence.evidence_id: evidence},
        DECISION_AT,
    )

    assert result.status == ValidationStatus.ABSTAINED
    assert result.fail_reason == FailReason.L4_NO_CROSS_VALIDATION


def _evidence(evidence_id: str, *, source_level: SourceLevel) -> Evidence:
    """Build a deterministic evidence fixture with the given source level.

    Args:
        evidence_id: str: .
        source_level: SourceLevel: .

    Returns:
        Evidence: .
    """
    chunk = make_chunk(
        document_id=f"doc-{evidence_id}",
        content="存在重大风险事件",
        symbol="000001.SZ",
        source_level=source_level,
        doc_type=DocType.FILING,
        source_url="https://example.com/filing.pdf",
        page=1,
        quote_span=(0, 8),
        available_at=DECISION_AT,
        published_at=DECISION_AT,
    )
    return Evidence.from_chunk(chunk).model_copy(update={"evidence_id": evidence_id})
