"""PostgreSQL repository tests for valuation discovery.

This module validates that the PostgreSQL valuation discovery repository
persists invalid quant input snapshots, effective assessment pointers,
assessment lineage atomically, and that the quant repository persists
runs and results.
"""

from __future__ import annotations

from datetime import UTC, datetime

from margin.storage.base import Base
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)
from margin.valuation_discovery.db_models import (
    EffectiveAssessmentPointerRow,
    QuantFactorValueRow,
    QuantInputSnapshotFactRow,
    QuantInputSnapshotRow,
    QuantScreenResultRow,
    QuantScreenRunRow,
    ValuationAssessmentEvidenceRow,
    ValuationAssessmentRow,
)
from margin.valuation_discovery.models import (
    DataStatus,
    EffectiveAssessmentPointer,
    QuantInputSnapshot,
    QuantResult,
    QuantRun,
    ResearchGuardrail,
    ScreeningStatus,
    ValuationAssessment,
    ValuationAssessmentEvidence,
)
from margin.valuation_discovery.quant.repository import SQLAlchemyQuantRepository
from margin.valuation_discovery.repository import SQLAlchemyValuationDiscoveryRepository


def test_postgres_repository_persists_invalid_quant_input_snapshot(database_url: str) -> None:
    """Verify the PostgreSQL repository persists an invalid quant input snapshot.

    Args:
        database_url: PostgreSQL connection URL for the isolated test database.

    Returns:
        None.
    """
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    with session_factory.begin() as session:
        session.query(QuantInputSnapshotFactRow).delete()
        session.query(QuantInputSnapshotRow).delete()

    repository = SQLAlchemyValuationDiscoveryRepository(session_factory)
    snapshot = QuantInputSnapshot(
        snapshot_id="qis-pg-1",
        scope_version_id="scope-v1",
        universe_snapshot_id="univ-snap-1",
        decision_at=datetime(2026, 6, 22, tzinfo=UTC),
        known_at=datetime(2026, 6, 22, tzinfo=UTC),
        security_ids=("000001.SZ",),
        required_indicators=("roe_ttm", "pb"),
        optional_indicators=("dividend_yield",),
        market_window_start=datetime(2025, 10, 5, tzinfo=UTC),
        market_window_end=datetime(2026, 6, 22, tzinfo=UTC),
        fact_refs=(
            {
                "fact_id": "fact-pb",
                "security_id": "000001.SZ",
                "indicator_id": "pb",
                "available_at": datetime(2026, 6, 1, tzinfo=UTC),
                "payload_hash": "sha256:pb",
            },
        ),
        fact_count=1,
        missing_required=("roe_ttm",),
        data_status=DataStatus.INSUFFICIENT,
        corporate_action_adjustment_version="adj-v1",
        industry_snapshot_id="industry-v1",
    )

    try:
        repository.add_quant_input_snapshot(snapshot)

        with session_factory() as session:
            row = session.get(QuantInputSnapshotRow, snapshot.snapshot_id)
            facts = session.query(QuantInputSnapshotFactRow).all()

        assert row is not None
        assert row.data_status == "insufficient"
        assert row.market_window_start == datetime(2025, 10, 5, tzinfo=UTC)
        assert row.corporate_action_adjustment_version == "adj-v1"
        assert len(facts) == 1
        assert facts[0].fact_id == "fact-pb"
    finally:
        with session_factory.begin() as session:
            session.query(QuantInputSnapshotFactRow).delete()
            session.query(QuantInputSnapshotRow).delete()
        engine.dispose()


def test_postgres_repository_persists_effective_assessment_pointer(
    database_url: str,
) -> None:
    """Verify the PostgreSQL repository persists an effective assessment pointer.

    Args:
        database_url: PostgreSQL connection URL for the isolated test database.

    Returns:
        None.
    """
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    with session_factory.begin() as session:
        session.query(EffectiveAssessmentPointerRow).delete()

    repository = SQLAlchemyValuationDiscoveryRepository(session_factory)
    pointer = EffectiveAssessmentPointer(
        pointer_id="eap-pg-1",
        security_id="000001.SZ",
        scope_version_id="scope-v1",
        effective_assessment_id="assess-new",
        effective_from=datetime(2026, 6, 22, tzinfo=UTC),
        assessment_freshness="current",
        stale_reason=None,
        last_successful_data_check_at=datetime(2026, 6, 22, 9, 30, tzinfo=UTC),
        last_successful_news_check_at=datetime(2026, 6, 22, 10, 0, tzinfo=UTC),
    )

    try:
        repository.add_effective_assessment_pointer(pointer)

        stored = repository.list_effective_assessment_pointers()

        assert stored == [pointer]
    finally:
        with session_factory.begin() as session:
            session.query(EffectiveAssessmentPointerRow).delete()
        engine.dispose()


def test_postgres_repository_atomically_publishes_assessment_lineage(
    database_url: str,
) -> None:
    """Verify assessment, evidence, and pointer publication is replay-idempotent.

    Args:
        database_url: PostgreSQL connection URL for the isolated test database.

    Returns:
        None.
    """
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    assessment_id = "assessment-publish-pg"
    pointer_id = "pointer-publish-pg"
    with session_factory.begin() as session:
        session.query(ValuationAssessmentEvidenceRow).filter_by(
            assessment_id=assessment_id
        ).delete()
        session.query(EffectiveAssessmentPointerRow).filter_by(
            pointer_id=pointer_id
        ).delete()
        session.query(ValuationAssessmentRow).filter_by(
            assessment_id=assessment_id
        ).delete()

    repository = SQLAlchemyValuationDiscoveryRepository(session_factory)
    assessment = ValuationAssessment(
        assessment_id=assessment_id,
        security_id="000001.SZ",
        scope_version_id="scope-v1",
        decision_at=datetime(2026, 6, 23, tzinfo=UTC),
        valuation_model="ai_delta_review_v0.2",
        conclusion="估值结论",
        evidence_refs=("evidence-pg",),
        created_at=datetime(2026, 6, 23, tzinfo=UTC),
    )
    edge = ValuationAssessmentEvidence(
        edge_id="edge-publish-pg",
        assessment_id=assessment_id,
        evidence_id="evidence-pg",
        role="supporting",
        created_at=datetime(2026, 6, 23, tzinfo=UTC),
    )
    pointer = EffectiveAssessmentPointer(
        pointer_id=pointer_id,
        security_id="000001.SZ",
        scope_version_id="scope-v1",
        effective_assessment_id=assessment_id,
        previous_assessment_id="assessment-old",
        effective_from=datetime(2026, 6, 23, tzinfo=UTC),
        assessment_freshness="current",
        created_at=datetime(2026, 6, 23, tzinfo=UTC),
    )

    try:
        repository.publish_valuation_result(
            assessment=assessment,
            evidence_edges=(edge,),
            pointer=pointer,
        )
        repository.publish_valuation_result(
            assessment=assessment,
            evidence_edges=(edge,),
            pointer=pointer,
        )

        assert repository.get_valuation_assessment(assessment_id) == assessment
        assert repository.list_valuation_assessment_evidence(
            assessment_id
        ) == [edge]
        assert pointer in repository.list_effective_assessment_pointers()
        assert repository.count_effective_assessments(
            scope_version_id="scope-v1",
            as_of=datetime(2026, 6, 23, tzinfo=UTC),
        ) >= 1
    finally:
        with session_factory.begin() as session:
            session.query(ValuationAssessmentEvidenceRow).filter_by(
                assessment_id=assessment_id
            ).delete()
            session.query(EffectiveAssessmentPointerRow).filter_by(
                pointer_id=pointer_id
            ).delete()
            session.query(ValuationAssessmentRow).filter_by(
                assessment_id=assessment_id
            ).delete()
        engine.dispose()


def test_postgres_quant_repository_persists_run_and_results(database_url: str) -> None:
    """Verify the PostgreSQL quant repository persists a run and its results.

    Args:
        database_url: PostgreSQL connection URL for the isolated test database.

    Returns:
        None.
    """
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    with session_factory.begin() as session:
        session.query(QuantFactorValueRow).delete()
        session.query(QuantScreenResultRow).delete()
        session.query(QuantScreenRunRow).delete()

    repository = SQLAlchemyQuantRepository(session_factory)
    quant_run = QuantRun(
        quant_run_id="qr-pg-1",
        input_snapshot_id="qis-pg-1",
        scope_version_id="scope-v1",
        strategy_version_id="strategy-v1",
        decision_at=datetime(2026, 6, 22, tzinfo=UTC),
        config_hash="sha256:config",
        status="completed",
    )
    result = QuantResult(
        result_id="qres-pg-1",
        quant_run_id=quant_run.quant_run_id,
        security_id="000001.SZ",
        final_score=82.5,
        quality_score=80.0,
        value_score=76.0,
        growth_score=70.0,
        momentum_score=66.0,
        risk_score=88.0,
        rank_overall=1,
        rank_in_industry=1,
        screening_status=ScreeningStatus.PASS,
        data_status=DataStatus.OK,
        research_guardrail=ResearchGuardrail.RESEARCH_ALLOWED,
        reason_summary="quality and risk are acceptable",
        factor_details={"quality": {"roe_ttm": 0.15}},
    )

    try:
        repository.add_run(quant_run)
        repository.add_results(quant_run.quant_run_id, (result,))

        with session_factory() as session:
            run_row = session.get(QuantScreenRunRow, quant_run.quant_run_id)
            result_rows = session.query(QuantScreenResultRow).all()
            factor_rows = session.query(QuantFactorValueRow).all()

        assert run_row is not None
        assert run_row.status == "completed"
        assert len(result_rows) == 1
        assert result_rows[0].screening_status == "pass"
        assert result_rows[0].rank_overall == 1
        assert len(factor_rows) >= 2
        assert repository.list_results(quant_run.quant_run_id)[0] == result
    finally:
        with session_factory.begin() as session:
            session.query(QuantFactorValueRow).delete()
            session.query(QuantScreenResultRow).delete()
            session.query(QuantScreenRunRow).delete()
        engine.dispose()
