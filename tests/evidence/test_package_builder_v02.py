"""v0.2 EvidencePackage model and builder tests.

Verifies that :class:`EvidencePackage` is frozen and tracks
``max_available_at``, that the builder rejects future-available evidence,
links news context to evidence, and is idempotent for the same persisted chunk.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from margin.evidence.models import (
    ClaimEvidenceRole,
    ClaimStatus,
    EvidencePackage,
    EvidencePackageQualityStatus,
)
from margin.evidence.package_builder import EvidencePackageBuilder
from margin.news.models import SourceLevel
from margin.vector.models import DocType, RetrievalResult, SourceLocator, make_chunk


def test_evidence_package_is_frozen_and_tracks_max_available_at() -> None:
    """Test that an evidence package is frozen and tracks max available_at."""
    package = EvidencePackage(
        package_id="pkg-1",
        version=1,
        security_id="000001.SZ",
        decision_at=datetime(2026, 6, 22, tzinfo=UTC),
        scope_hash="scope-hash",
        questions=("经营现金流是否改善？",),
        evidence_ids=("ev-1", "ev-2"),
        claim_ids=("cl-1",),
        conflict_ids=(),
        coverage=0.75,
        quality_status=EvidencePackageQualityStatus.USABLE,
        max_available_at=datetime(2026, 6, 21, tzinfo=UTC),
        retrieval_audit_id="ret-1",
    )

    assert package.model_config["frozen"] is True
    assert package.max_available_at is not None
    assert package.max_available_at < package.decision_at
    assert ClaimStatus.ABSTAINED.value == "abstained"
    assert ClaimEvidenceRole.SUPPORTS.value == "supports"


def test_builder_rejects_future_available_evidence() -> None:
    """Test that the builder rejects evidence available after the decision time."""
    evidence_repository = FakeEvidenceRepository()
    builder = EvidencePackageBuilder(
        FakeVectorRepository({("future", "000001.SZ")}),
        evidence_repository,
    )

    package = builder.build(
        security_id="000001.SZ",
        decision_at=datetime(2026, 6, 22, tzinfo=UTC),
        questions=("风险事件？",),
        retrieval_results=[
            retrieval_result(
                "future",
                available_at=datetime(2026, 6, 23, tzinfo=UTC),
            )
        ],
        news_bundle_id="bundle-1",
        scope_hash="scope-1",
    )

    assert package.quality_status == EvidencePackageQualityStatus.ABSTAIN_REQUIRED
    assert package.evidence_ids == ()
    assert evidence_repository.evidences == {}


def test_builder_links_news_context_to_evidence() -> None:
    """Test that the builder links news context bundles to evidence items."""
    evidence_repository = FakeEvidenceRepository()
    builder = EvidencePackageBuilder(
        FakeVectorRepository({("chunk-1", "000001.SZ")}),
        evidence_repository,
    )

    package = builder.build(
        security_id="000001.SZ",
        decision_at=datetime(2026, 6, 22, tzinfo=UTC),
        questions=("公司公告有什么变化？",),
        retrieval_results=[
            retrieval_result(
                "chunk-1",
                available_at=datetime(2026, 6, 21, tzinfo=UTC),
            )
        ],
        news_bundle_id="bundle-1",
        scope_hash="scope-1",
    )

    links = evidence_repository.list_news_context_evidence("bundle-1")
    assert len(package.evidence_ids) == 1
    assert links[0].evidence_id == package.evidence_ids[0]
    assert package.coverage == 1.0


def test_builder_is_idempotent_for_the_same_persisted_chunk() -> None:
    """Test that the builder is idempotent when building from the same persisted chunk."""
    evidence_repository = FakeEvidenceRepository()
    builder = EvidencePackageBuilder(
        FakeVectorRepository({("chunk-1", "000001.SZ")}),
        evidence_repository,
    )
    kwargs = {
        "security_id": "000001.SZ",
        "decision_at": datetime(2026, 6, 22, tzinfo=UTC),
        "questions": ("公司公告有什么变化？",),
        "retrieval_results": [
            retrieval_result(
                "chunk-1",
                available_at=datetime(2026, 6, 21, tzinfo=UTC),
            )
        ],
        "news_bundle_id": None,
        "scope_hash": "scope-1",
    }

    first = builder.build(**kwargs)
    second = builder.build(**kwargs)

    assert first == second
    assert len(evidence_repository.evidences) == 1


class FakeVectorRepository:
    """Fake vector repository that checks chunk-security links by membership."""

    def __init__(self, links: set[tuple[str, str]]) -> None:
        """Initialize the fake repository with a set of known chunk-security links."""
        self.links = links

    def chunk_has_security_link(self, chunk_id: str, security_id: str) -> bool:
        """Return whether the given chunk is linked to the given security."""
        return (chunk_id, security_id) in self.links


class FakeEvidenceRepository:
    """Fake evidence repository that stores evidences, packages, and news links in memory."""

    def __init__(self) -> None:
        """Initialize the fake repository with empty stores."""
        self.evidences = {}
        self.packages = []
        self.news_links = []

    def add_evidence(self, evidence) -> None:
        """Store an evidence item, rejecting mutation of an existing one."""
        existing = self.evidences.get(evidence.evidence_id)
        if existing is not None and existing != evidence:
            raise ValueError("evidence is immutable")
        self.evidences[evidence.evidence_id] = evidence

    def add_evidence_package(self, package: EvidencePackage) -> None:
        """Append an evidence package to the in-memory store."""
        self.packages.append(package)

    def link_news_context_evidence(self, bundle_id: str, evidence_id: str) -> None:
        """Record a news-context to evidence link."""
        self.news_links.append((bundle_id, evidence_id))

    def list_news_context_evidence(self, bundle_id: str):
        """List evidence links for the given news-context bundle."""
        return [
            SimpleNamespace(bundle_id=stored_bundle_id, evidence_id=evidence_id)
            for stored_bundle_id, evidence_id in self.news_links
            if stored_bundle_id == bundle_id
        ]


def retrieval_result(chunk_id: str, *, available_at: datetime) -> RetrievalResult:
    """Build a deterministic retrieval result fixture for the given chunk ID."""
    content = f"{chunk_id} 公司公告内容"
    chunk = make_chunk(
        document_id=f"doc-{chunk_id}",
        content=content,
        source_level=SourceLevel.L1,
        doc_type=DocType.NEWS,
        available_at=available_at,
        published_at=available_at,
        source_url="https://example.com/news",
        snapshot_id=f"snap-{chunk_id}",
        snapshot_hash="sha256:snapshot",
        locator=SourceLocator(paragraph_index=0, quote_span=(0, len(content))),
    ).model_copy(update={"chunk_id": chunk_id, "symbol": "000001.SZ"})
    return RetrievalResult(chunk=chunk, score=0.9)
