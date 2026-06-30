"""Deterministic v0.2 evidence conflict classification."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from margin.evidence.models import (
    Claim,
    ClaimEvidenceLink,
    ClaimEvidenceRole,
    ConflictSeverity,
    EvidenceConflict,
)


class EvidenceConflictClassifier:
    """Classify structured claim/evidence link conflicts."""

    def classify(
        self,
        claim: Claim,
        links: Sequence[ClaimEvidenceLink],
        *,
        package_id: str,
        version: int,
    ) -> list[EvidenceConflict]:
        """Return conflicts implied by support/refute role combinations.

        A conflict is recorded when the same claim has both a SUPPORTS and a
        REFUTES evidence link. The conflict severity is always HIGH.

        Args:
            claim: The claim whose evidence links are being classified.
            links: Sequence of claim-evidence role links to inspect.
            package_id: Identifier of the frozen evidence package.
            version: Version number of the frozen evidence package.

        Returns:
            A list of ``EvidenceConflict`` instances. Empty when no support/refute
            pair is found.
        """
        supports = [link for link in links if link.role == ClaimEvidenceRole.SUPPORTS]
        refutes = [link for link in links if link.role == ClaimEvidenceRole.REFUTES]
        if not supports or not refutes:
            return []
        support = supports[0]
        refute = refutes[0]
        return [
            EvidenceConflict(
                conflict_id=_conflict_id(
                    claim.claim_id,
                    support.evidence_id,
                    refute.evidence_id,
                ),
                package_id=package_id,
                version=version,
                security_id=claim.symbol or "",
                evidence_id=support.evidence_id,
                conflicting_evidence_id=refute.evidence_id,
                reason="support_refute_conflict",
                severity=ConflictSeverity.HIGH,
            )
        ]


def _conflict_id(claim_id: str, evidence_id: str, conflicting_evidence_id: str) -> str:
    """Compute a deterministic conflict ID from claim and evidence identifiers."""
    payload = "|".join([claim_id, evidence_id, conflicting_evidence_id])
    return "conf_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
