"""v0.2 deterministic evidence conflict classifier tests.

Verifies that the :class:`EvidenceConflictClassifier` detects support/refute
conflicts and assigns the correct severity.
"""

from __future__ import annotations

from margin.evidence.conflicts import EvidenceConflictClassifier
from margin.evidence.models import (
    ClaimEvidenceLink,
    ClaimEvidenceRole,
    ConflictSeverity,
    make_claim,
)


def test_support_and_refute_links_create_high_severity_conflict() -> None:
    """Test that support and refute links create a high-severity conflict.

    Returns:
        None: .
    """
    claim = make_claim(
        statement="收入增长",
        evidence_ids=["ev-positive", "ev-negative"],
        symbol="000001.SZ",
    ).model_copy(update={"claim_id": "cl-1"})
    links = [
        ClaimEvidenceLink(
            claim_id="cl-1",
            evidence_id="ev-positive",
            role=ClaimEvidenceRole.SUPPORTS,
            rank=1,
        ),
        ClaimEvidenceLink(
            claim_id="cl-1",
            evidence_id="ev-negative",
            role=ClaimEvidenceRole.REFUTES,
            rank=2,
        ),
    ]

    conflicts = EvidenceConflictClassifier().classify(
        claim,
        links,
        package_id="pkg-1",
        version=1,
    )

    assert len(conflicts) == 1
    assert conflicts[0].severity == ConflictSeverity.HIGH
    assert conflicts[0].evidence_id == "ev-positive"
    assert conflicts[0].conflicting_evidence_id == "ev-negative"
    assert conflicts[0].reason == "support_refute_conflict"
