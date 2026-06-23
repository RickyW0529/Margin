"""v0.2 PostgreSQL repository tests for evidence packages and news links."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from margin.evidence.db_models import (
    ClaimEvidenceLinkRow,
    EvidenceClaimRow,
    EvidenceConflictRow,
    EvidencePackageItemRow,
    EvidencePackageRow,
    EvidenceRecordRow,
    NewsContextEvidenceRow,
)
from margin.evidence.models import (
    ClaimEvidenceRole,
    ClaimStatus,
    ClaimType,
    ConflictSeverity,
    Evidence,
    EvidenceConflict,
    EvidencePackage,
    EvidencePackageQualityStatus,
    FactOrInference,
    make_claim,
)
from margin.evidence.repository import EvidenceRepository
from margin.news.db_models import NewsContextBundleRow, NewsRefreshRunRow
from margin.news.models import SourceLevel
from margin.storage.base import Base
from margin.storage.database import DatabaseSettings, create_database_engine, create_session_factory
from margin.vector.models import DocType, make_chunk

DECISION_AT = datetime(2026, 6, 22, tzinfo=UTC)


@pytest.fixture
def evidence_repository(database_url: str) -> Iterator[EvidenceRepository]:
    """evidence repository."""
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    with session_factory.begin() as session:
        for row in (
            NewsContextEvidenceRow,
            EvidenceConflictRow,
            ClaimEvidenceLinkRow,
            EvidencePackageItemRow,
            EvidencePackageRow,
            EvidenceClaimRow,
            EvidenceRecordRow,
            NewsContextBundleRow,
            NewsRefreshRunRow,
        ):
            session.query(row).delete()
        session.add(
            NewsRefreshRunRow(
                run_id="run-1",
                scope_version_id="scope-1",
                quant_run_id="quant-1",
                decision_at=DECISION_AT,
                status="completed",
                target_count=1,
                completed_count=1,
                failed_final_count=0,
                created_at=DECISION_AT,
                started_at=DECISION_AT,
                finished_at=DECISION_AT,
                error_summary={},
            )
        )
        session.flush()
        session.add(
            NewsContextBundleRow(
                bundle_id="bundle-1",
                run_id="run-1",
                security_id="000001.SZ",
                target_completion_state="completed",
                can_support_verified_carry_forward=True,
                incomplete_reason_codes=[],
                created_at=DECISION_AT,
            )
        )
    yield EvidenceRepository(session_factory)
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_repository_persists_package_and_news_context_link(
    evidence_repository: EvidenceRepository,
) -> None:
    """repository persists package and news context link."""
    evidence = _evidence()
    package = _package(evidence.evidence_id)

    evidence_repository.add_evidence(evidence)
    evidence_repository.add_evidence_package(package)
    evidence_repository.link_news_context_evidence("bundle-1", evidence.evidence_id)

    assert evidence_repository.get_evidence_package("pkg-1", 1) == package
    [link] = evidence_repository.list_news_context_evidence("bundle-1")
    assert link.bundle_id == "bundle-1"
    assert link.evidence_id == evidence.evidence_id


def test_repository_round_trips_structured_locator_fields(
    evidence_repository: EvidenceRepository,
) -> None:
    """repository round trips structured locator fields."""
    evidence = _evidence().model_copy(
        update={
            "evidence_id": "ev-structured",
            "bbox": (1.0, 2.0, 3.0, 4.0),
            "dom_path": "/html/body/p[1]",
            "column_id": "revenue",
        }
    )

    evidence_repository.add_evidence(evidence)

    assert evidence_repository.get_evidence(evidence.evidence_id) == evidence


def test_repository_rejects_package_mutation(
    evidence_repository: EvidenceRepository,
) -> None:
    """repository rejects package mutation."""
    package = _package("ev-1")

    evidence_repository.add_evidence_package(package)

    with pytest.raises(ValueError, match="immutable"):
        evidence_repository.add_evidence_package(
            package.model_copy(update={"coverage": 0.5})
        )


def test_repository_creates_append_only_package_revision(
    evidence_repository: EvidenceRepository,
) -> None:
    """repository creates append only package revision."""
    first_evidence = _evidence()
    second_evidence = _evidence().model_copy(update={"evidence_id": "ev-2"})
    package = _package(first_evidence.evidence_id)

    evidence_repository.add_evidence(first_evidence)
    evidence_repository.add_evidence(second_evidence)
    evidence_repository.add_evidence_package(package)

    revision = evidence_repository.create_package_revision(
        package.package_id,
        (second_evidence.evidence_id,),
        retrieval_audit_id="ret-2",
    )

    assert revision.package_id == package.package_id
    assert revision.version == 2
    assert revision.parent_package_id == package.package_id
    assert revision.evidence_ids == ("ev-1", "ev-2")
    assert revision.added_evidence_ids == ("ev-2",)
    assert revision.retrieval_audit_id == "ret-2"
    assert evidence_repository.get_evidence_package("pkg-1", 1) == package
    assert evidence_repository.get_evidence_package("pkg-1", 2) == revision


def test_repository_persists_claim_status_and_claim_evidence_link(
    evidence_repository: EvidenceRepository,
) -> None:
    """repository persists claim status and claim evidence link."""
    evidence = _evidence()
    claim = make_claim(
        statement="收入增长",
        claim_type=ClaimType.GROWTH_SIGNAL,
        fact_or_inference=FactOrInference.FACT,
        evidence_ids=[evidence.evidence_id],
        confidence=0.8,
        symbol="000001.SZ",
        effective_at=DECISION_AT,
    ).model_copy(update={"claim_id": "cl-1", "status": ClaimStatus.CONFLICTED})

    evidence_repository.add_evidence(evidence)
    evidence_repository.add_claim(claim)
    evidence_repository.link_claim_evidence(
        "cl-1",
        evidence.evidence_id,
        role=ClaimEvidenceRole.SUPPORTS,
        rank=2,
    )

    assert evidence_repository.get_claim("cl-1").status == ClaimStatus.CONFLICTED
    [link] = evidence_repository.list_claim_evidence("cl-1")
    assert link.evidence_id == evidence.evidence_id
    assert link.role == ClaimEvidenceRole.SUPPORTS
    assert link.rank == 2


def test_repository_persists_evidence_conflicts(
    evidence_repository: EvidenceRepository,
) -> None:
    """repository persists evidence conflicts."""
    package = _package("ev-positive").model_copy(
        update={"conflict_ids": ("conf-1",)}
    )
    conflict = EvidenceConflict(
        conflict_id="conf-1",
        package_id=package.package_id,
        version=package.version,
        security_id="000001.SZ",
        evidence_id="ev-positive",
        conflicting_evidence_id="ev-negative",
        reason="support_refute_conflict",
        severity=ConflictSeverity.HIGH,
        created_at=DECISION_AT,
    )

    evidence_repository.add_evidence(
        _evidence().model_copy(update={"evidence_id": "ev-positive"})
    )
    evidence_repository.add_evidence(
        _evidence().model_copy(update={"evidence_id": "ev-negative"})
    )
    evidence_repository.add_evidence_package(package)
    evidence_repository.add_evidence_conflict(conflict)

    assert evidence_repository.list_evidence_conflicts("pkg-1", 1) == [conflict]


def _evidence() -> Evidence:
    """evidence."""
    chunk = make_chunk(
        document_id="doc-1",
        content="经营现金流改善",
        symbol="000001.SZ",
        source_level=SourceLevel.L1,
        doc_type=DocType.FILING,
        source_url="https://example.com/filing.pdf",
        page=1,
        quote_span=(0, 6),
        published_at=DECISION_AT,
        available_at=DECISION_AT,
    )
    return Evidence.from_chunk(chunk).model_copy(update={"evidence_id": "ev-1"})


def _package(evidence_id: str) -> EvidencePackage:
    """package."""
    return EvidencePackage(
        package_id="pkg-1",
        version=1,
        security_id="000001.SZ",
        decision_at=DECISION_AT,
        scope_hash="scope-1",
        questions=("公司公告有什么变化？",),
        evidence_ids=(evidence_id,),
        claim_ids=(),
        conflict_ids=(),
        coverage=1.0,
        quality_status=EvidencePackageQualityStatus.USABLE,
        max_available_at=DECISION_AT,
        retrieval_audit_id="ret-1",
    )
