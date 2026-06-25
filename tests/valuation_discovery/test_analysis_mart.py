"""Analysis Mart persistence and publishing tests."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from margin.storage.base import Base
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)
from margin.valuation_discovery.analysis_mart import (
    AnalysisEvidenceLink,
    AnalysisFinding,
    AnalysisMartBundle,
    AnalysisMartPublisher,
    AnalysisMetric,
    AnalysisSnapshot,
    MemoryAnalysisMartRepository,
    QuantFeatureRow,
    QuantFeatureSnapshot,
    SQLAlchemyAnalysisMartRepository,
)
from margin.valuation_discovery.db_models import (
    AnalysisEvidenceLinkRow,
    AnalysisFindingRow,
    AnalysisMetricRow,
    AnalysisSnapshotRow,
    QuantFeatureRowRow,
    QuantFeatureSnapshotRow,
)
from margin.valuation_discovery.models import (
    DataStatus,
    QuantResult,
    ResearchGuardrail,
    ScreeningStatus,
)

DECISION_AT = datetime(2026, 6, 24, 8, 0, tzinfo=UTC)


def test_memory_feature_mart_persists_snapshot_idempotently() -> None:
    """Fourth-layer quant feature snapshots can be replayed safely."""
    repository = MemoryAnalysisMartRepository()
    snapshot, rows = _feature_snapshot()

    repository.upsert_feature_snapshot(snapshot, rows)
    repository.upsert_feature_snapshot(snapshot, rows)

    assert repository.get_feature_snapshot("qfsnap-1") == snapshot
    assert repository.latest_feature_snapshot(
        scope_version_id="scope-v1",
        as_of=DECISION_AT,
    ) == snapshot
    assert repository.list_feature_rows("qfsnap-1") == list(rows)


def test_memory_feature_mart_rejects_conflicting_snapshot_replay() -> None:
    """Feature mart rows are append-only and cannot be overwritten."""
    repository = MemoryAnalysisMartRepository()
    snapshot, rows = _feature_snapshot()
    repository.upsert_feature_snapshot(snapshot, rows)
    conflicting = QuantFeatureSnapshot(
        **{
            **snapshot.__dict__,
            "input_hash": "sha256:changed",
        }
    )

    with pytest.raises(ValueError, match="conflicting quant feature snapshot"):
        repository.upsert_feature_snapshot(conflicting, rows)


def test_postgres_feature_mart_persists_snapshot(database_url: str) -> None:
    """PostgreSQL repository stores feature snapshots and rows."""
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    snapshot, rows = _feature_snapshot(snapshot_id="qfsnap-pg")

    with session_factory.begin() as session:
        _delete_feature_rows(session, "qfsnap-pg")

    repository = SQLAlchemyAnalysisMartRepository(session_factory)
    try:
        repository.upsert_feature_snapshot(snapshot, rows)
        repository.upsert_feature_snapshot(snapshot, rows)

        assert repository.get_feature_snapshot("qfsnap-pg") == snapshot
        assert repository.list_feature_rows("qfsnap-pg") == list(rows)
    finally:
        with session_factory.begin() as session:
            _delete_feature_rows(session, "qfsnap-pg")
        engine.dispose()


def test_postgres_feature_mart_rolls_back_partial_child_conflict(
    database_url: str,
) -> None:
    """Feature ETL never leaves a snapshot header without its rows."""
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    snapshot, rows = _feature_snapshot(snapshot_id="qfsnap-rollback")
    existing_snapshot, existing_rows = _feature_snapshot(snapshot_id="qfsnap-existing")
    existing_snapshot = QuantFeatureSnapshot(
        **{**existing_snapshot.__dict__, "row_count": 1}
    )
    existing_row = QuantFeatureRow(
        **{
            **existing_rows[0].__dict__,
            "row_id": rows[0].row_id,
            "features": {"pe_ttm": 99.0},
        }
    )

    with session_factory.begin() as session:
        _delete_feature_rows(session, "qfsnap-rollback")
        _delete_feature_rows(session, "qfsnap-existing")

    repository = SQLAlchemyAnalysisMartRepository(session_factory)
    try:
        repository.upsert_feature_snapshot(existing_snapshot, (existing_row,))

        with pytest.raises(ValueError, match="conflicting quant feature row"):
            repository.upsert_feature_snapshot(snapshot, rows)

        assert repository.get_feature_snapshot("qfsnap-rollback") is None
        assert repository.get_feature_snapshot("qfsnap-existing") == existing_snapshot
    finally:
        with session_factory.begin() as session:
            _delete_feature_rows(session, "qfsnap-rollback")
            _delete_feature_rows(session, "qfsnap-existing")
        engine.dispose()


def test_memory_analysis_mart_persists_bundle_idempotently() -> None:
    """A complete fourth-layer bundle can be replayed without duplication."""
    repository = MemoryAnalysisMartRepository()
    bundle = _bundle()

    repository.upsert_bundle(bundle)
    repository.upsert_bundle(bundle)

    assert repository.get_snapshot("asnap-1") == bundle.snapshot
    assert repository.latest_snapshot(
        security_id="000001.SZ",
        scope_version_id="scope-v1",
        as_of=DECISION_AT,
    ) == bundle.snapshot
    assert repository.list_metrics("asnap-1") == list(bundle.metrics)
    assert repository.list_findings("asnap-1") == list(bundle.findings)
    assert repository.list_evidence_links("asnap-1") == list(bundle.evidence_links)


def test_memory_analysis_mart_rejects_conflicting_replay() -> None:
    """Append-only Analysis Mart rows cannot be overwritten with new content."""
    repository = MemoryAnalysisMartRepository()
    bundle = _bundle()
    repository.upsert_bundle(bundle)
    conflicting = AnalysisMartBundle(
        snapshot=bundle.snapshot.with_result_hash("sha256:changed"),
        metrics=bundle.metrics,
        findings=bundle.findings,
        evidence_links=bundle.evidence_links,
    )

    with pytest.raises(ValueError, match="conflicting analysis snapshot"):
        repository.upsert_bundle(conflicting)


def test_memory_analysis_mart_latest_snapshot_uses_decision_time() -> None:
    """The latest effective analysis snapshot is selected by decision time."""
    repository = MemoryAnalysisMartRepository()
    older = _bundle(snapshot_id="asnap-old", decision_at=datetime(2026, 6, 23, tzinfo=UTC))
    newer = _bundle(snapshot_id="asnap-new", decision_at=DECISION_AT)
    repository.upsert_bundle(newer)
    repository.upsert_bundle(older)

    assert repository.latest_snapshot(
        security_id="000001.SZ",
        scope_version_id="scope-v1",
        as_of=DECISION_AT,
    ) == newer.snapshot
    assert repository.latest_snapshot(
        security_id="000001.SZ",
        scope_version_id="scope-v1",
        as_of=datetime(2026, 6, 23, 12, 0, tzinfo=UTC),
    ) == older.snapshot


def test_postgres_analysis_mart_persists_bundle(database_url: str) -> None:
    """PostgreSQL repository stores snapshots, metrics, findings, and links."""
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    bundle = _bundle(snapshot_id="asnap-pg")

    with session_factory.begin() as session:
        _delete_bundle_rows(session, "asnap-pg")

    repository = SQLAlchemyAnalysisMartRepository(session_factory)
    try:
        repository.upsert_bundle(bundle)
        repository.upsert_bundle(bundle)

        assert repository.get_snapshot("asnap-pg") == bundle.snapshot
        assert repository.list_metrics("asnap-pg") == list(bundle.metrics)
        assert repository.list_findings("asnap-pg") == list(bundle.findings)
        assert repository.list_evidence_links("asnap-pg") == list(bundle.evidence_links)
    finally:
        with session_factory.begin() as session:
            _delete_bundle_rows(session, "asnap-pg")
        engine.dispose()


def test_postgres_analysis_mart_rolls_back_partial_child_conflict(
    database_url: str,
) -> None:
    """Analysis-result ETL commits snapshot and child rows atomically."""
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    bundle = _bundle(snapshot_id="asnap-rollback")
    existing = _bundle(snapshot_id="asnap-existing")
    existing_metric = AnalysisMetric(
        **{
            **existing.metrics[0].__dict__,
            "metric_id": bundle.metrics[0].metric_id,
        }
    )
    existing = AnalysisMartBundle(
        snapshot=existing.snapshot,
        metrics=(existing_metric,),
        findings=existing.findings,
        evidence_links=existing.evidence_links,
    )

    with session_factory.begin() as session:
        _delete_bundle_rows(session, "asnap-rollback")
        _delete_bundle_rows(session, "asnap-existing")

    repository = SQLAlchemyAnalysisMartRepository(session_factory)
    try:
        repository.upsert_bundle(existing)

        with pytest.raises(ValueError, match="conflicting analysis metric"):
            repository.upsert_bundle(bundle)

        assert repository.get_snapshot("asnap-rollback") is None
        assert repository.get_snapshot("asnap-existing") == existing.snapshot
    finally:
        with session_factory.begin() as session:
            _delete_bundle_rows(session, "asnap-rollback")
            _delete_bundle_rows(session, "asnap-existing")
        engine.dispose()


def test_analysis_mart_publisher_materializes_quant_result() -> None:
    """Quant output is transformed into AI-ready fourth-layer analysis rows."""
    repository = MemoryAnalysisMartRepository()
    publisher = AnalysisMartPublisher(repository)
    result = QuantResult(
        result_id="quant-result-publish",
        quant_run_id="quant-run-publish",
        security_id="000001.SZ",
        final_score=88.4,
        quality_score=76.0,
        value_score=91.0,
        growth_score=54.0,
        momentum_score=62.0,
        risk_score=80.0,
        rank_overall=12,
        rank_in_industry=3,
        screening_status=ScreeningStatus.PASS,
        data_status=DataStatus.OK,
        risk_flags=("low_liquidity_watch",),
        review_required=True,
        review_reasons=("material_quant_change",),
        research_guardrail=ResearchGuardrail.RESEARCH_ALLOWED,
        reason_summary="估值和分红因子贡献较高。",
        factor_details={
            "name": "平安银行",
            "industry_id": "bank",
            "ai_quant_profile": {
                "strategy_profile": "manual_all_a_no_market_cap_no_top_n",
                "candidate": True,
                "rank": 12,
                "scores": {
                    "manual_all_a_score": 88.4,
                    "value": 91.0,
                    "dividend": 80.0,
                    "liquidity": 70.0,
                },
                "raw_factors": {
                    "pe_ttm": 8.2,
                    "pb": 0.68,
                    "dividend_yield": 0.045,
                    "avg_amount_20d": 820000000.0,
                },
                "research_hints": ["核对低估值是否由资产质量折价导致"],
            },
        },
        created_at=DECISION_AT,
    )

    snapshot = publisher.publish_quant_result(
        scope_version_id="scope-v1",
        decision_at=DECISION_AT,
        trading_date=date(2026, 6, 24),
        quant_result=result,
        input_snapshot_id="quant-input-1",
        strategy_version_id="strategy-v1",
        config_hash="sha256:config",
        input_hash="sha256:input",
        evidence_ids=("evidence-1",),
    )

    assert repository.get_snapshot(snapshot.analysis_snapshot_id) == snapshot
    assert snapshot.summary["screening_status"] == "pass"
    assert snapshot.summary["final_score"] == 88.4
    assert snapshot.summary["rank_overall"] == 12
    assert snapshot.summary["research_hints"] == ["核对低估值是否由资产质量折价导致"]
    metrics = repository.list_metrics(snapshot.analysis_snapshot_id)
    assert {metric.metric_code for metric in metrics} >= {
        "final_score",
        "score_value",
        "raw_pe_ttm",
        "raw_avg_amount_20d",
    }
    [finding] = repository.list_findings(snapshot.analysis_snapshot_id)
    assert finding.finding_type == "quant_screening"
    assert finding.evidence_ids == ("evidence-1",)
    links = repository.list_evidence_links(snapshot.analysis_snapshot_id)
    assert {link.source_type for link in links} >= {"quant_result", "quant_input_snapshot"}


def _bundle(
    *,
    snapshot_id: str = "asnap-1",
    decision_at: datetime = DECISION_AT,
) -> AnalysisMartBundle:
    snapshot = AnalysisSnapshot(
        analysis_snapshot_id=snapshot_id,
        security_id="000001.SZ",
        scope_version_id="scope-v1",
        decision_at=decision_at,
        trading_date=date(2026, 6, 24),
        analysis_version="analysis-mart-v0.3.0",
        analysis_kind="quant_snapshot",
        quant_run_id="quant-run-1",
        quant_result_id="quant-result-1",
        input_snapshot_id="quant-input-1",
        strategy_version_id="strategy-v1",
        config_hash="sha256:config",
        input_hash="sha256:input",
        result_hash="sha256:result",
        summary={
            "screening_status": "pass",
            "final_score": 88.4,
            "rank": 12,
            "key_points": ["估值分位较低", "流动性满足研究要求"],
        },
        quality_flags=("pit_valid",),
        created_at=decision_at,
    )
    metric = AnalysisMetric(
        metric_id=f"metric-{snapshot_id}-pe",
        analysis_snapshot_id=snapshot_id,
        metric_code="pe_ttm",
        metric_name="PE TTM",
        metric_group="valuation",
        numeric_value=8.2,
        unit="ratio",
        direction="lower_is_better",
        percentile_market=0.18,
        percentile_industry=0.22,
        rank_market=520,
        rank_industry=14,
        source_refs=(
            {
                "source_type": "canonical_fact",
                "source_id": "fact-pe",
                "indicator_id": "pe_ttm",
            },
        ),
        detail={"raw_value": 8.2},
        created_at=decision_at,
    )
    finding = AnalysisFinding(
        finding_id=f"finding-{snapshot_id}-valuation",
        analysis_snapshot_id=snapshot_id,
        finding_type="valuation_signal",
        severity="positive",
        title="低估值候选",
        description="PE 和 PB 均处于全市场较低分位，值得 AI 复核基本面质量。",
        confidence=0.74,
        evidence_ids=("evidence-1",),
        source_refs=(
            {
                "source_type": "quant_result",
                "source_id": "quant-result-1",
            },
        ),
        detail={"related_metrics": [metric.metric_id]},
        created_at=decision_at,
    )
    link = AnalysisEvidenceLink(
        link_id=f"alink-{snapshot_id}-valuation",
        analysis_snapshot_id=snapshot_id,
        finding_id=finding.finding_id,
        metric_id=metric.metric_id,
        evidence_id="evidence-1",
        source_type="quant_result",
        source_id="quant-result-1",
        role="supports",
        detail={"reason": "quant finding links to frozen evidence"},
        created_at=decision_at,
    )
    return AnalysisMartBundle(
        snapshot=snapshot,
        metrics=(metric,),
        findings=(finding,),
        evidence_links=(link,),
    )


def _feature_snapshot(
    *,
    snapshot_id: str = "qfsnap-1",
    decision_at: datetime = DECISION_AT,
) -> tuple[QuantFeatureSnapshot, tuple[QuantFeatureRow, ...]]:
    snapshot = QuantFeatureSnapshot(
        feature_snapshot_id=snapshot_id,
        scope_version_id="scope-v1",
        universe_snapshot_id="universe-v1",
        decision_at=decision_at,
        known_at=decision_at,
        trading_date=date(2026, 6, 24),
        feature_set_version_id="feature-set-v1",
        feature_schema_version="quant-feature-mart-v0.3.0",
        source_layer="third_layer",
        input_hash="sha256:features",
        row_count=2,
        feature_columns=(
            "pe_ttm",
            "avg_amount_20d",
            "return_6m_ex_1m",
            "is_st",
        ),
        lineage_summary={
            "canonical_fact_count": 6,
            "history_indicator_ids": ["close", "amount", "adj_factor"],
        },
        quality_flags=("pit_valid",),
        created_at=decision_at,
    )
    rows = (
        QuantFeatureRow(
            row_id=f"{snapshot_id}-000001",
            feature_snapshot_id=snapshot_id,
            security_id="000001.SZ",
            symbol="000001.SZ",
            name="平安银行",
            industry_id="bank",
            features={
                "pe_ttm": 8.2,
                "avg_amount_20d": 820000000.0,
                "return_6m_ex_1m": 0.12,
                "is_st": False,
            },
            source_refs=(
                {
                    "source_type": "canonical_fact",
                    "source_id": "fact-pe",
                    "indicator_id": "pe_ttm",
                },
            ),
            quality_flags=("pit_valid",),
            created_at=decision_at,
        ),
        QuantFeatureRow(
            row_id=f"{snapshot_id}-000002",
            feature_snapshot_id=snapshot_id,
            security_id="000002.SZ",
            symbol="000002.SZ",
            name="ST示例",
            industry_id="software",
            features={
                "pe_ttm": 20.0,
                "avg_amount_20d": 80000000.0,
                "return_6m_ex_1m": -0.03,
                "is_st": True,
            },
            source_refs=(),
            quality_flags=("st_security",),
            created_at=decision_at,
        ),
    )
    return snapshot, rows


def _delete_bundle_rows(session, snapshot_id: str) -> None:
    session.query(AnalysisEvidenceLinkRow).filter_by(
        analysis_snapshot_id=snapshot_id
    ).delete()
    session.query(AnalysisFindingRow).filter_by(
        analysis_snapshot_id=snapshot_id
    ).delete()
    session.query(AnalysisMetricRow).filter_by(
        analysis_snapshot_id=snapshot_id
    ).delete()
    session.query(AnalysisSnapshotRow).filter_by(
        analysis_snapshot_id=snapshot_id
    ).delete()


def _delete_feature_rows(session, snapshot_id: str) -> None:
    session.query(QuantFeatureRowRow).filter_by(
        feature_snapshot_id=snapshot_id
    ).delete()
    session.query(QuantFeatureSnapshotRow).filter_by(
        feature_snapshot_id=snapshot_id
    ).delete()
