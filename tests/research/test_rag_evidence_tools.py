"""Scoped RAG evidence retrieval tool tests."""

from __future__ import annotations

from datetime import UTC, datetime

from margin.evidence.models import EvidencePackage
from margin.news.models import SourceLevel
from margin.research.evidence_tools import register_rag_evidence_tools
from margin.research.service import ResearchContextSnapshot, _default_tool_factory
from margin.research.tools.definitions import ToolCapability, ToolDefinitionRegistry
from margin.research.tools.factory import ScopedToolFactory
from margin.research.tools.policy import ToolPolicyEngine
from margin.vector.models import DocType, RetrievalResult, SourceLocator, make_chunk

DECISION_AT = datetime(2026, 6, 30, tzinfo=UTC)


def test_rag_evidence_tool_returns_agent_ready_evidence_blocks() -> None:
    """The scoped tool should return locatable evidence blocks for agents."""
    registry = ToolDefinitionRegistry()
    package_builder = FakeEvidencePackageBuilder()
    register_rag_evidence_tools(
        registry,
        retrieval_tool=FakeRetrievalTool(
            [
                _retrieval_result(
                    "chunk-1",
                    content="营业收入 2024 年同比下降 10.9%，净利润同比下降 4.2%。",
                    score=0.91,
                )
            ]
        ),
        package_builder=package_builder,
        scope_hash_factory=lambda payload: "scope-test",
    )
    session = ScopedToolFactory(
        tool_registry=registry,
        policy=ToolPolicyEngine(),
    ).create_session(
        graph_run_id="graph-rag",
        node_name="retrieve_evidence",
        security_id="000001.SZ",
        decision_at=DECISION_AT,
        grants={ToolCapability.EVIDENCE_RETRIEVE},
    )

    result = session.call(
        "rag_evidence_retrieve",
        {
            "security_id": "000001.SZ",
            "decision_at": DECISION_AT.isoformat(),
            "query": "平安银行 2024 营业收入 净利润",
            "questions": ["业绩是否改善？"],
            "doc_types": ["annual_report"],
            "top_k": 3,
            "build_package": True,
        },
    )

    assert result.success is True
    assert result.data["package_id"] == "pkg-test"
    assert result.data["quality_status"] == "usable"
    assert result.data["coverage"] == 1.0
    assert result.data["evidence_ids"] == ["ev-chunk-1"]
    assert result.data["retrieval"]["query"] == "平安银行 2024 营业收入 净利润"
    assert result.data["retrieval"]["top_k"] == 3
    assert result.data["retrieval"]["doc_types"] == ["annual_report"]
    assert result.data["evidence_blocks"] == [
        {
            "rank": 1,
            "evidence_id": "ev-chunk-1",
            "chunk_id": "chunk-1",
            "document_id": "doc-chunk-1",
            "source_url": "https://example.com/report.pdf",
            "source_name": "cninfo",
            "source_level": 2,
            "doc_type": "annual_report",
            "content": "营业收入 2024 年同比下降 10.9%，净利润同比下降 4.2%。",
            "content_hash": result.data["evidence_blocks"][0]["content_hash"],
            "score": 0.91,
            "vector_score": 0.88,
            "keyword_score": 0.5,
            "published_at": "2026-06-29T00:00:00+00:00",
            "available_at": "2026-06-29T00:00:00+00:00",
            "snapshot_id": "snap-chunk-1",
            "snapshot_hash": "sha256:snapshot",
            "locator": {
                "page": None,
                "section": None,
                "paragraph_index": 0,
                "table_id": None,
                "row_id": None,
                "quote_span": [0, 34],
            },
        }
    ]
    assert package_builder.calls[0]["questions"] == ("业绩是否改善？",)
    assert package_builder.calls[0]["retrieval_results"][0].chunk.chunk_id == "chunk-1"


def test_rag_evidence_tool_uses_gap_query_for_supplemental_retrieval() -> None:
    """Supplemental retrieval should query evidence gaps when no explicit query is given."""
    retrieval_tool = FakeRetrievalTool([])
    registry = ToolDefinitionRegistry()
    register_rag_evidence_tools(registry, retrieval_tool=retrieval_tool)
    session = ScopedToolFactory(
        tool_registry=registry,
        policy=ToolPolicyEngine(),
    ).create_session(
        graph_run_id="graph-rag",
        node_name="additional_evidence_retrieval",
        security_id="000001.SZ",
        decision_at=DECISION_AT,
        grants={ToolCapability.EVIDENCE_RETRIEVE},
    )

    result = session.call(
        "rag_evidence_retrieve",
        {
            "security_id": "000001.SZ",
            "decision_at": DECISION_AT.isoformat(),
            "questions": ["风险是否扩大？"],
            "evidence_gaps": ["缺少拨备覆盖率解释", "缺少不良贷款变化"],
            "supplemental": True,
            "build_package": False,
        },
    )

    assert result.success is True
    assert retrieval_tool.calls[0]["query"] == "缺少拨备覆盖率解释\n缺少不良贷款变化"
    assert result.data["quality_status"] == "abstain_required"
    assert result.data["evidence_blocks"] == []


def test_rag_evidence_tool_is_available_from_manifest() -> None:
    """The registry helper should expose the tool under EVIDENCE_RETRIEVE grants."""
    registry = ToolDefinitionRegistry()
    register_rag_evidence_tools(registry, retrieval_tool=FakeRetrievalTool([]))
    session = ScopedToolFactory(
        tool_registry=registry,
        policy=ToolPolicyEngine(),
    ).create_session(
        graph_run_id="graph-rag",
        node_name="retrieve_evidence",
        security_id="000001.SZ",
        decision_at=DECISION_AT,
        grants={ToolCapability.EVIDENCE_RETRIEVE},
    )

    manifest_names = {tool.name for tool in session.manifest().tools}

    assert "rag_evidence_retrieve" in manifest_names


def test_default_tool_factory_uses_rag_retrieval_when_dependencies_are_provided() -> None:
    """The graph's existing evidence_retrieve tool should use RAG when wired."""
    retrieval_tool = FakeRetrievalTool(
        [
            _retrieval_result(
                "chunk-graph",
                content="不良贷款率 2024 年为 1.06%，拨备覆盖率为 250.71%。",
                score=0.87,
            )
        ]
    )
    context = ResearchContextSnapshot(
        context_snapshot_id="context-rag",
        security_id="000001.SZ",
        scope_version_id="scope-v1",
        decision_at=DECISION_AT,
        payload_hash="sha256:context",
        payload={},
    )
    session = _default_tool_factory(
        context,
        rag_retrieval_tool=retrieval_tool,
        rag_scope_hash_factory=lambda payload: "scope-rag",
    ).create_session(
        graph_run_id="graph-rag",
        node_name="retrieve_evidence",
        security_id="000001.SZ",
        decision_at=DECISION_AT,
        grants={ToolCapability.EVIDENCE_RETRIEVE},
    )

    manifest_names = {tool.name for tool in session.manifest().tools}
    result = session.call(
        "evidence_retrieve",
        {
            "security_id": "000001.SZ",
            "decision_at": DECISION_AT.isoformat(),
            "questions": ["资产质量是否恶化？"],
        },
    )

    assert {"evidence_retrieve", "rag_evidence_retrieve"} <= manifest_names
    assert result.success is True
    assert result.data["scope_hash"] == "scope-rag"
    assert result.data["evidence_blocks"][0]["chunk_id"] == "chunk-graph"
    assert retrieval_tool.calls[0]["query"] == "资产质量是否恶化？"


class FakeRetrievalTool:
    """Fake retrieval tool recording calls and returning fixed results."""

    def __init__(self, results: list[RetrievalResult]) -> None:
        """Initialize the fake with fixed results."""
        self.results = results
        self.calls: list[dict] = []

    def search(
        self,
        *,
        query: str,
        symbol: str,
        decision_at: datetime,
        doc_types: list[str] | None,
        top_k: int,
        prefer_official: bool,
    ) -> list[RetrievalResult]:
        """Record arguments and return fixed retrieval results."""
        self.calls.append(
            {
                "query": query,
                "symbol": symbol,
                "decision_at": decision_at,
                "doc_types": doc_types,
                "top_k": top_k,
                "prefer_official": prefer_official,
            }
        )
        return self.results[:top_k]


class FakeEvidencePackageBuilder:
    """Fake package builder returning a stable package for tests."""

    def __init__(self) -> None:
        """Initialize call storage."""
        self.calls: list[dict] = []

    def build(self, **kwargs) -> EvidencePackage:
        """Record the build call and return a package."""
        self.calls.append(kwargs)
        return EvidencePackage(
            package_id="pkg-test",
            version=1,
            security_id=kwargs["security_id"],
            decision_at=kwargs["decision_at"],
            scope_hash=kwargs["scope_hash"],
            questions=tuple(kwargs["questions"]),
            evidence_ids=tuple(
                f"ev-{result.chunk.chunk_id}"
                for result in kwargs["retrieval_results"]
            ),
            claim_ids=(),
            conflict_ids=(),
            coverage=1.0 if kwargs["retrieval_results"] else 0.0,
            quality_status="usable" if kwargs["retrieval_results"] else "abstain_required",
            max_available_at=max(
                (result.chunk.available_at for result in kwargs["retrieval_results"]),
                default=None,
            ),
            retrieval_audit_id=kwargs.get("retrieval_audit_id"),
            added_evidence_ids=tuple(
                f"ev-{result.chunk.chunk_id}"
                for result in kwargs["retrieval_results"]
            ),
        )


def _retrieval_result(
    chunk_id: str,
    *,
    content: str,
    score: float,
) -> RetrievalResult:
    """Build one retrieval result with complete source locator metadata."""
    published_at = datetime(2026, 6, 29, tzinfo=UTC)
    chunk = make_chunk(
        document_id=f"doc-{chunk_id}",
        content=content,
        symbol="000001.SZ",
        source_level=SourceLevel.L2,
        doc_type=DocType.ANNUAL_REPORT,
        published_at=published_at,
        available_at=published_at,
        source_url="https://example.com/report.pdf",
        source_name="cninfo",
        snapshot_id=f"snap-{chunk_id}",
        snapshot_hash="sha256:snapshot",
        locator=SourceLocator(paragraph_index=0, quote_span=(0, 34)),
    ).model_copy(update={"chunk_id": chunk_id})
    return RetrievalResult(
        chunk=chunk,
        score=score,
        vector_score=0.88,
        keyword_score=0.5,
        time_decay=0.9,
        source_quality=0.8,
        entity_match=1.0,
        rank=1,
    )
