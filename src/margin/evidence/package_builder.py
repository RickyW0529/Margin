"""Build frozen v0.2 evidence packages from retrieval results."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from margin.evidence.models import (
    Claim,
    ClaimEvidenceLink,
    Evidence,
    EvidencePackage,
    EvidencePackageQualityStatus,
)
from margin.news.models import ensure_utc


class EvidencePackageBuilder:
    """Normalize retrieval output into immutable EvidencePackage versions.."""

    def __init__(self, vector_repository: Any, evidence_repository: Any) -> None:
        """Initialize the builder with vector and evidence repositories.

        Args:
            vector_repository: Any: .
            evidence_repository: Any: .

        Returns:
            None: .
        """
        self._vector_repository = vector_repository
        self._evidence_repository = evidence_repository

    def build(
        self,
        *,
        security_id: str,
        decision_at: datetime,
        questions: tuple[str, ...],
        retrieval_results: list[Any],
        news_bundle_id: str | None,
        scope_hash: str,
        retrieval_audit_id: str | None = None,
        parent_package_id: str | None = None,
        version: int = 1,
        claims: tuple[Claim, ...] = (),
        claim_evidence_links: tuple[ClaimEvidenceLink, ...] = (),
    ) -> EvidencePackage:
        """Build and persist a frozen evidence package.

        Args:
            security_id: str: .
            decision_at: datetime: .
            questions: tuple[str, ...]: .
            retrieval_results: list[Any]: .
            news_bundle_id: str | None: .
            scope_hash: str: .
            retrieval_audit_id: str | None: .
            parent_package_id: str | None: .
            version: int: .
            claims: Explicit structured claims produced by a claim extraction stage.
            claim_evidence_links: Explicit support/refute/context links for those claims.

        Returns:
            EvidencePackage: .
        """
        normalized_decision_at = ensure_utc(decision_at)
        valid_evidence: list[Evidence] = []

        for result in retrieval_results:
            chunk = result.chunk
            if ensure_utc(chunk.available_at) > normalized_decision_at:
                continue
            if not self._chunk_matches_security(chunk, security_id):
                continue
            evidence = Evidence.from_chunk(chunk).model_copy(
                update={
                    "evidence_id": make_stable_evidence_id(security_id, chunk),
                    "symbol": security_id,
                    # Chunk has no persisted retrieval timestamp. Reuse its
                    # immutable availability time so rebuilding the same
                    # canonical Evidence ID remains idempotent.
                    "retrieved_at": ensure_utc(chunk.available_at),
                }
            )
            self._evidence_repository.add_evidence(evidence)
            if news_bundle_id:
                self._evidence_repository.link_news_context_evidence(
                    news_bundle_id,
                    evidence.evidence_id,
                )
            valid_evidence.append(evidence)

        evidence_ids = tuple(evidence.evidence_id for evidence in valid_evidence)
        claim_ids = self._persist_claim_graph(
            claims=claims,
            links=claim_evidence_links,
            evidence_ids=evidence_ids,
        )
        requested_count = len(retrieval_results)
        coverage = len(evidence_ids) / requested_count if requested_count else 0.0
        package = EvidencePackage(
            package_id=_stable_package_id(
                security_id=security_id,
                decision_at=normalized_decision_at,
                scope_hash=scope_hash,
                questions=questions,
                evidence_ids=evidence_ids,
                claim_ids=claim_ids,
                parent_package_id=parent_package_id,
                version=version,
            ),
            version=version,
            security_id=security_id,
            decision_at=normalized_decision_at,
            scope_hash=scope_hash,
            questions=tuple(questions),
            evidence_ids=evidence_ids,
            claim_ids=claim_ids,
            conflict_ids=(),
            coverage=coverage,
            quality_status=_quality_status(len(evidence_ids), requested_count),
            max_available_at=max(
                (evidence.available_at for evidence in valid_evidence),
                default=None,
            ),
            retrieval_audit_id=retrieval_audit_id,
            parent_package_id=parent_package_id,
            added_evidence_ids=evidence_ids,
        )
        add_package = getattr(self._evidence_repository, "add_evidence_package", None)
        if callable(add_package):
            add_package(package)
        return package

    def _persist_claim_graph(
        self,
        *,
        claims: tuple[Claim, ...],
        links: tuple[ClaimEvidenceLink, ...],
        evidence_ids: tuple[str, ...],
    ) -> tuple[str, ...]:
        """Persist only explicitly supplied claims with complete evidence role links."""
        if not claims and not links:
            return ()
        claims_by_id = {claim.claim_id: claim for claim in claims}
        if len(claims_by_id) != len(claims):
            raise ValueError("duplicate claim IDs are not allowed")
        evidence_id_set = set(evidence_ids)
        links_by_claim: dict[str, list[ClaimEvidenceLink]] = {}
        for link in links:
            if link.claim_id not in claims_by_id:
                raise ValueError(f"claim link references unknown claim: {link.claim_id}")
            if link.evidence_id not in evidence_id_set:
                raise ValueError(
                    f"claim link references evidence outside package: {link.evidence_id}"
                )
            links_by_claim.setdefault(link.claim_id, []).append(link)

        for claim in claims:
            claim_links = links_by_claim.get(claim.claim_id, [])
            if not claim_links:
                raise ValueError(f"claim has no evidence role links: {claim.claim_id}")
            if not set(claim.evidence_ids).issubset(evidence_id_set):
                raise ValueError(f"claim references evidence outside package: {claim.claim_id}")
            linked_evidence_ids = {link.evidence_id for link in claim_links}
            if set(claim.evidence_ids) != linked_evidence_ids:
                raise ValueError(f"claim evidence IDs do not match role links: {claim.claim_id}")
            self._evidence_repository.add_claim(claim)
            for link in claim_links:
                self._evidence_repository.link_claim_evidence(
                    link.claim_id,
                    link.evidence_id,
                    role=link.role,
                    rank=link.rank,
                )
        return tuple(claim.claim_id for claim in claims)

    def _chunk_matches_security(self, chunk: Any, security_id: str) -> bool:
        """Check whether a chunk is linked to the requested security.

        Args:
            chunk: Any: .
            security_id: str: .

        Returns:
            bool: .
        """
        has_link = getattr(self._vector_repository, "chunk_has_security_link", None)
        if callable(has_link):
            return bool(has_link(chunk.chunk_id, security_id))
        return getattr(chunk, "symbol", None) == security_id


def make_stable_evidence_id(security_id: str, chunk: Any) -> str:
    """Compute a deterministic evidence ID from security and chunk identity.

    Args:
        security_id: str: .
        chunk: Any: .

    Returns:
        str: .
    """
    payload = "|".join(
        [
            security_id,
            chunk.chunk_id,
            getattr(chunk, "snapshot_id", "") or "",
            chunk.content_hash,
        ]
    )
    return "ev_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _stable_package_id(
    *,
    security_id: str,
    decision_at: datetime,
    scope_hash: str,
    questions: tuple[str, ...],
    evidence_ids: tuple[str, ...],
    claim_ids: tuple[str, ...],
    parent_package_id: str | None,
    version: int,
) -> str:
    """Compute a deterministic package ID from scope and evidence identity.

    Args:
        security_id: str: .
        decision_at: datetime: .
        scope_hash: str: .
        questions: tuple[str, ...]: .
        evidence_ids: tuple[str, ...]: .
        claim_ids: tuple[str, ...]: .
        parent_package_id: str | None: .
        version: int: .

    Returns:
        str: .
    """
    identity_parts = [
        security_id,
        decision_at.isoformat(),
        scope_hash,
        "\n".join(questions),
        ",".join(evidence_ids),
    ]
    if claim_ids:
        identity_parts.append(",".join(claim_ids))
    identity_parts.extend((parent_package_id or "", str(version)))
    payload = "|".join(identity_parts)
    return "pkg_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _quality_status(
    valid_evidence_count: int,
    requested_result_count: int,
) -> EvidencePackageQualityStatus:
    """Determine the package quality status from valid vs requested evidence counts.

    Args:
        valid_evidence_count: int: .
        requested_result_count: int: .

    Returns:
        EvidencePackageQualityStatus: .
    """
    if valid_evidence_count == 0:
        return EvidencePackageQualityStatus.ABSTAIN_REQUIRED
    if valid_evidence_count < requested_result_count:
        return EvidencePackageQualityStatus.PARTIAL
    return EvidencePackageQualityStatus.USABLE
