"""Production research-context adapter integration tests.

This module validates that the research context builder adapter freezes
quant, news, evidence, and previous state into a durable context snapshot
and publishes an analysis snapshot atomically.
"""

from __future__ import annotations

from datetime import UTC, datetime

from margin.evidence.models import (
    EvidencePackage,
    EvidencePackageQualityStatus,
)
from margin.news.models import (
    NewsContextBundle,
    NewsContextDocument,
    NewsTarget,
    SourceLevel,
    TargetTriggerType,
)
from margin.storage.base import Base
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)
from margin.valuation_discovery.adapters import ResearchContextBuilderAdapter
from margin.valuation_discovery.analysis_mart import SQLAlchemyAnalysisMartRepository
from margin.valuation_discovery.db_models import (
    AnalysisEvidenceLinkRow,
    AnalysisFindingRow,
    AnalysisMetricRow,
    AnalysisSnapshotRow,
    EffectiveAssessmentPointerRow,
    QuantInputSnapshotRow,
    QuantScreenResultRow,
    QuantScreenRunRow,
    ResearchContextSnapshotRow,
)
from margin.valuation_discovery.models import (
    DataStatus,
    QuantResult,
    ResearchGuardrail,
    ScreeningStatus,
)

DECISION_AT = datetime(2026, 6, 22, tzinfo=UTC)


def test_context_builder_freezes_quant_news_evidence_and_previous_state(
    database_url: str,
) -> None:
    """Verify context snapshots contain only durable inputs required by AI review.

    Args:
        database_url: str: .

    Returns:
        None: .
    """
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    _clean(session_factory)
    _seed_quant_state(session_factory)
    adapter = ResearchContextBuilderAdapter(
        session_factory,
        news_bundle_builder=FakeNewsBundleBuilder(),
        retrieval_tool=FakeRetrievalTool(),
        evidence_package_builder=FakeEvidencePackageBuilder(),
        analysis_mart_repository=SQLAlchemyAnalysisMartRepository(session_factory),
    )
    result = QuantResult(
        result_id="result-current",
        quant_run_id="quant-current",
        security_id="000001.SZ",
        final_score=82.0,
        screening_status=ScreeningStatus.PASS,
        data_status=DataStatus.OK,
        review_required=True,
        research_guardrail=ResearchGuardrail.RESEARCH_ALLOWED,
        factor_details={
            "ai_quant_profile": {
                "strategy_profile": "manual_all_a_no_market_cap_no_top_n",
                "execution_boundary": "research_only_no_order",
                "scores": {"manual_all_a_score": 78.5},
                "raw_factors": {"market_cap": 120_000_000_000.0},
            }
        },
    )
    target = NewsTarget(
        scope_version_id="scope-1",
        quant_run_id="quant-current",
        security_id="000001.SZ",
        symbol="000001.SZ",
        name="平安银行",
        trigger_type=TargetTriggerType.REVIEW_DUE,
        decision_at=DECISION_AT,
        priority=120,
        filing_event_ids=("filing-discovered",),
    )

    [context_id] = adapter.build(
        scope_version_id="scope-1",
        quant_run_id="quant-current",
        news_refresh_run_id="news-run-1",
        decision_at=DECISION_AT,
        targets=(target,),
        results=(result,),
    )

    with session_factory() as session:
        row = session.get(ResearchContextSnapshotRow, context_id)
    assert row is not None
    payload = row.payload_json
    assert payload["quant_input_snapshot_id"] == "input-current"
    assert payload["previous_effective_assessment_id"] == "assessment-old"
    assert payload["news_context_bundle_id"] == "bundle-1"
    assert payload["evidence_package_id"] == "package-1"
    assert payload["evidence_ids"] == ["evidence-1"]
    assert payload["new_filing_document_ids"] == ["filing-discovered", "event-1"]
    assert payload["quant_ai_profile"]["scores"]["manual_all_a_score"] == 78.5
    assert payload["quant_ai_profile"]["raw_factors"]["market_cap"] == 120_000_000_000.0
    assert payload["analysis_snapshot_id"].startswith("asnap_")
    assert payload["analysis_summary"]["screening_status"] == "pass"
    assert payload["analysis_summary"]["final_score"] == 82.0
    assert payload["analysis_summary"]["strategy_profile"] == (
        "manual_all_a_no_market_cap_no_top_n"
    )
    assert payload["material_quant_change"] is True
    assert payload["news_target_complete"] is True
    with session_factory() as session:
        analysis_row = session.get(
            AnalysisSnapshotRow,
            payload["analysis_snapshot_id"],
        )
    assert analysis_row is not None
    assert analysis_row.quant_result_id == "result-current"
    assert adapter.list_context_snapshot_ids(
        scope_version_id="scope-1",
        quant_run_id="quant-current",
    ) == (context_id,)
    engine.dispose()


class FakeNewsBundleBuilder:
    """Return a complete durable news context.."""

    def build_for_run(self, *, run_id: str, security_id: str) -> NewsContextBundle:
        """Build and return a deterministic news context bundle for the given run.

        Args:
            run_id: str: .
            security_id: str: .

        Returns:
            NewsContextBundle: .
        """
        assert run_id == "news-run-1"
        return NewsContextBundle(
            bundle_id="bundle-1",
            run_id=run_id,
            security_id=security_id,
            target_completion_state="complete",
            can_support_verified_carry_forward=True,
            documents=(
                NewsContextDocument(
                    event_id="event-1",
                    title="公司公告",
                    source_level=SourceLevel.L1,
                    materiality_score=0.9,
                    novelty_score=0.8,
                    published_at=DECISION_AT,
                ),
            ),
        )


class FakeRetrievalTool:
    """Record the PIT-constrained evidence retrieval call.."""

    def search(self, **kwargs):
        """Return a deterministic retrieval result after asserting PIT constraints.

        Args:
            **kwargs: Any: .

        Returns:
            Any: .
        """
        assert kwargs["symbol"] == "000001.SZ"
        assert kwargs["decision_at"] == DECISION_AT
        return ["retrieval-result"]


class FakeEvidencePackageBuilder:
    """Freeze one evidence package from retrieval output.."""

    def build(self, **kwargs) -> EvidencePackage:
        """Build and return a deterministic evidence package from retrieval results.

        Args:
            **kwargs: Any: .

        Returns:
            EvidencePackage: .
        """
        assert kwargs["retrieval_results"] == ["retrieval-result"]
        assert kwargs["news_bundle_id"] == "bundle-1"
        return EvidencePackage(
            package_id="package-1",
            version=1,
            security_id="000001.SZ",
            decision_at=DECISION_AT,
            scope_hash=kwargs["scope_hash"],
            questions=kwargs["questions"],
            evidence_ids=("evidence-1",),
            claim_ids=(),
            conflict_ids=(),
            coverage=1.0,
            quality_status=EvidencePackageQualityStatus.USABLE,
            max_available_at=DECISION_AT,
            retrieval_audit_id=None,
        )


def _clean(session_factory) -> None:
    """Remove rows owned by this test.

    Args:
        session_factory: Any: .

    Returns:
        None: .
    """
    with session_factory.begin() as session:
        for model in (
            ResearchContextSnapshotRow,
            AnalysisEvidenceLinkRow,
            AnalysisFindingRow,
            AnalysisMetricRow,
            AnalysisSnapshotRow,
            EffectiveAssessmentPointerRow,
            QuantScreenResultRow,
            QuantScreenRunRow,
            QuantInputSnapshotRow,
        ):
            session.query(model).delete()


def _seed_quant_state(session_factory) -> None:
    """Seed current/previous quant lineage and the prior effective conclusion.

    Args:
        session_factory: Any: .

    Returns:
        None: .
    """
    with session_factory.begin() as session:
        session.add(
            QuantInputSnapshotRow(
                snapshot_id="input-current",
                scope_version_id="scope-1",
                universe_snapshot_id="universe-1",
                decision_at=DECISION_AT,
                known_at=DECISION_AT,
                security_ids=["000001.SZ"],
                required_indicators=["n_income_attr_p", "roe_ttm", "pe_ttm"],
                optional_indicators=[],
                fact_count=2,
                missing_required=[],
                data_status=DataStatus.OK.value,
                quality_flags=[],
                freshness_flags=[],
                pit_validation_errors=[],
                input_hash="sha256:input",
                created_at=DECISION_AT,
            )
        )
        session.add_all(
            [
                QuantScreenRunRow(
                    quant_run_id="quant-previous",
                    input_snapshot_id="input-current",
                    scope_version_id="scope-1",
                    strategy_version_id="strategy-1",
                    decision_at=datetime(2026, 6, 21, tzinfo=UTC),
                    config_hash="sha256:config",
                    status="completed",
                    created_at=datetime(2026, 6, 21, tzinfo=UTC),
                ),
                QuantScreenRunRow(
                    quant_run_id="quant-current",
                    input_snapshot_id="input-current",
                    scope_version_id="scope-1",
                    strategy_version_id="strategy-1",
                    decision_at=DECISION_AT,
                    config_hash="sha256:config",
                    status="completed",
                    created_at=DECISION_AT,
                ),
            ]
        )
        session.add(
            QuantScreenResultRow(
                result_id="result-previous",
                quant_run_id="quant-previous",
                security_id="000001.SZ",
                final_score=70.0,
                screening_status=ScreeningStatus.NEAR_THRESHOLD.value,
                data_status=DataStatus.OK.value,
                risk_flags=[],
                review_required=False,
                review_reasons=[],
                research_guardrail=ResearchGuardrail.LIMITED_RESEARCH.value,
                reason_summary="previous",
                factor_details={},
                created_at=datetime(2026, 6, 21, tzinfo=UTC),
            )
        )
        session.add(
            EffectiveAssessmentPointerRow(
                pointer_id="pointer-old",
                security_id="000001.SZ",
                scope_version_id="scope-1",
                effective_assessment_id="assessment-old",
                effective_from=datetime(2026, 6, 21, tzinfo=UTC),
                assessment_freshness="current",
                created_at=datetime(2026, 6, 21, tzinfo=UTC),
            )
        )
