#!/usr/bin/env python3
"""Database-backed smoke for the v0.2 RAG evidence pipeline."""

from __future__ import annotations

import argparse
import hashlib
from datetime import UTC, datetime

from margin.evidence.models import (
    ClaimEvidenceRole,
    ClaimStatus,
    ClaimType,
    FactOrInference,
    make_claim,
)
from margin.evidence.package_builder import EvidencePackageBuilder
from margin.evidence.repository import EvidenceRepository
from margin.evidence.validator import (
    CitationValidator,
    ValidationAuditor,
    ValidationStatus,
)
from margin.news.models import SourceLevel
from margin.settings import MarginSettings
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)
from margin.vector.models import (
    Chunk,
    ChunkSecurityLink,
    DocType,
    RetrievalResult,
    SourceLocator,
    TrustLevel,
    compute_chunk_hash,
    make_stable_chunk_id,
)
from margin.vector.repository import VectorRepository

PARSER_VERSION = "smoke-rag-evidence-v0.2"
QUESTION = "经营现金流是否改善？"
STATEMENT = "样例公告披露经营现金流保持改善。"


def main() -> int:
    """Run the smoke and return a process exit code."""
    args = _parse_args()
    decision_at = _parse_decision_at(args.decision_at)
    database_url = args.database_url or str(MarginSettings().database_url)
    engine = create_database_engine(DatabaseSettings(url=database_url))
    session_factory = create_session_factory(engine)
    vector_repository = VectorRepository(session_factory, dimension=1)
    evidence_repository = EvidenceRepository(session_factory)

    package_id = "none"
    evidence_count = 0
    claim_status = ClaimStatus.UNSUPPORTED
    validation_status = ValidationStatus.FAIL

    try:
        chunk = _resolve_chunk(
            vector_repository,
            chunk_id=args.chunk_id,
            create_sample=args.create_sample,
            security_id=args.security_id,
            decision_at=decision_at,
        )
        if chunk is None:
            _print_result(
                status="blocked",
                package_id=package_id,
                evidence_count=evidence_count,
                claim_status=claim_status,
                validation_status=validation_status,
            )
            return 2

        package = EvidencePackageBuilder(
            vector_repository,
            evidence_repository,
        ).build(
            security_id=args.security_id,
            decision_at=decision_at,
            questions=(QUESTION,),
            retrieval_results=[RetrievalResult(chunk=chunk, score=1.0, rank=1)],
            news_bundle_id=None,
            scope_hash=_scope_hash(args.security_id),
            retrieval_audit_id="smoke-rag-evidence",
        )
        package_id = package.package_id
        evidence_count = len(package.evidence_ids)
        if not package.evidence_ids:
            _print_result(
                status="blocked",
                package_id=package_id,
                evidence_count=evidence_count,
                claim_status=claim_status,
                validation_status=validation_status,
            )
            return 2

        evidence = evidence_repository.get_evidence(package.evidence_ids[0])
        if evidence is None:
            raise RuntimeError("persisted evidence could not be reloaded")

        claim = make_claim(
            statement=STATEMENT,
            claim_type=ClaimType.CASH_FLOW_IMPROVEMENT,
            fact_or_inference=FactOrInference.FACT,
            evidence_ids=[evidence.evidence_id],
            confidence=0.9,
            symbol=args.security_id,
            effective_at=decision_at,
        ).model_copy(
            update={"claim_id": _claim_id(package.package_id, evidence.evidence_id)}
        )
        validation = CitationValidator().validate_claim(
            claim,
            {evidence.evidence_id: evidence},
            decision_at,
        )
        validation_status = validation.status
        claim_status = _claim_status(validation.status)
        persisted_claim = claim.model_copy(update={"status": claim_status})
        evidence_repository.add_claim(persisted_claim)
        evidence_repository.link_claim_evidence(
            persisted_claim.claim_id,
            evidence.evidence_id,
            role=ClaimEvidenceRole.SUPPORTS,
        )
        evidence_repository.add_validation_audit(
            ValidationAuditor().log(validation)
        )
    except Exception:  # noqa: BLE001 - smoke output intentionally omits sensitive detail
        _print_result(
            status="failed",
            package_id=package_id,
            evidence_count=evidence_count,
            claim_status=claim_status,
            validation_status=validation_status,
        )
        return 3
    finally:
        engine.dispose()

    _print_result(
        status="ok" if validation_status == ValidationStatus.PASS else "failed",
        package_id=package_id,
        evidence_count=evidence_count,
        claim_status=claim_status,
        validation_status=validation_status,
    )
    return 0 if validation_status == ValidationStatus.PASS else 3


def _parse_args() -> argparse.Namespace:
    """parse args."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default="")
    parser.add_argument("--security-id", required=True)
    parser.add_argument("--decision-at", required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--chunk-id", default="")
    source.add_argument("--create-sample", action="store_true")
    return parser.parse_args()


def _parse_decision_at(value: str) -> datetime:
    """parse decision at."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _resolve_chunk(
    repository: VectorRepository,
    *,
    chunk_id: str,
    create_sample: bool,
    security_id: str,
    decision_at: datetime,
) -> Chunk | None:
    """resolve chunk."""
    if not create_sample:
        return repository.get_chunk(chunk_id)

    chunk = _build_sample_chunk(security_id, decision_at)
    repository.upsert_chunks(
        [chunk],
        links=[
            ChunkSecurityLink(
                chunk_id=chunk.chunk_id,
                security_id=security_id,
                link_type="smoke_subject",
                confidence=1.0,
            )
        ],
    )
    return chunk


def _build_sample_chunk(security_id: str, available_at: datetime) -> Chunk:
    """build sample chunk."""
    content = "正式公告样例：本期经营现金流保持改善。"
    content_hash = compute_chunk_hash(content)
    document_id = f"smoke_rag_evidence_{security_id}"
    return Chunk(
        chunk_id=make_stable_chunk_id(
            document_id=document_id,
            content_hash=content_hash,
            parser_version=PARSER_VERSION,
            chunk_index=0,
        ),
        document_id=document_id,
        content=content,
        content_hash=content_hash,
        symbol=security_id,
        source_level=SourceLevel.L1,
        doc_type=DocType.FILING,
        published_at=available_at,
        available_at=available_at,
        source_url="https://www.szse.cn/disclosure/smoke-rag-evidence",
        source_name="Margin official sample",
        snapshot_id=f"smoke-rag-evidence-{security_id}",
        snapshot_hash=content_hash,
        page=1,
        quote_span=(0, len(content)),
        locator=SourceLocator(page=1, quote_span=(0, len(content))),
        trust_level=TrustLevel.TRUSTED_OFFICIAL_CONTENT,
        keywords=("正式公告", "经营现金流"),
        chunk_index=0,
        total_chunks=1,
    )


def _scope_hash(security_id: str) -> str:
    """scope hash."""
    payload = f"{security_id}|{QUESTION}"
    return "scope_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _claim_id(package_id: str, evidence_id: str) -> str:
    """claim id."""
    payload = f"{package_id}|{evidence_id}|{STATEMENT}"
    return "clm_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _claim_status(validation_status: ValidationStatus) -> ClaimStatus:
    """claim status."""
    if validation_status == ValidationStatus.PASS:
        return ClaimStatus.SUPPORTED
    if validation_status == ValidationStatus.ABSTAINED:
        return ClaimStatus.ABSTAINED
    return ClaimStatus.UNSUPPORTED


def _print_result(
    *,
    status: str,
    package_id: str,
    evidence_count: int,
    claim_status: ClaimStatus,
    validation_status: ValidationStatus,
) -> None:
    """print result."""
    print(
        f"status={status} "
        f"package_id={package_id} "
        f"evidence_count={evidence_count} "
        f"claim_status={claim_status.value} "
        f"validation_status={validation_status.value}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
