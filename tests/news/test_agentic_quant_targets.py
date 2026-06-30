"""Quant result to news target selection tests."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from margin.data.db_models import (
    CompanyPoolMemberRow,
    CompanyPoolSnapshotRow,
    DataSyncRunRow,
    SecurityMasterRow,
)
from margin.news.models import TargetTriggerType
from margin.news.quant_targets import SQLAlchemyQuantNewsTargetRepository
from margin.storage.base import Base
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)
from margin.valuation_discovery.db_models import (
    QuantScreenResultRow,
    QuantScreenRunRow,
)


@pytest.fixture
def target_repository(database_url: str) -> Iterator[SQLAlchemyQuantNewsTargetRepository]:
    """Create a seeded quant target repository."""
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    with session_factory.begin() as session:
        session.query(QuantScreenResultRow).delete()
        session.query(QuantScreenRunRow).delete()
        decision_at = datetime(2026, 6, 29, tzinfo=UTC)
        session.add(
            QuantScreenRunRow(
                quant_run_id="qr_test",
                input_snapshot_id="qis_test",
                scope_version_id="scope_v1",
                strategy_version_id="strategy_v1",
                decision_at=decision_at,
                config_hash="sha256:config",
                status="completed",
                created_at=decision_at,
            )
        )
        for result_id, security_id, status, name, symbol in (
            ("res_pass", "000001.SZ", "pass", "平安银行", "000001.SZ"),
            ("res_near", "000002.SZ", "near_threshold", "万科A", "000002.SZ"),
            ("res_reject", "000003.SZ", "reject", "国农科技", "000003.SZ"),
        ):
            session.add(
                QuantScreenResultRow(
                    result_id=result_id,
                    quant_run_id="qr_test",
                    security_id=security_id,
                    final_score=80.0,
                    screening_status=status,
                    data_status="valid",
                    risk_flags=[],
                    review_required=False,
                    review_reasons=[],
                    research_guardrail="research_allowed",
                    reason_summary="seeded",
                    factor_details={
                        "name": name,
                        "symbol": symbol,
                        "aliases": [name],
                        "industry_terms": ["银行" if security_id == "000001.SZ" else "地产"],
                    },
                    created_at=decision_at,
                )
            )
    yield SQLAlchemyQuantNewsTargetRepository(session_factory)
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_quant_target_loader_defaults_to_pass_only(
    target_repository: SQLAlchemyQuantNewsTargetRepository,
) -> None:
    """Default news target loading includes PASS and excludes near-threshold rows."""
    decision_at = datetime(2026, 6, 29, tzinfo=UTC)

    targets = target_repository.list_targets(
        scope_version_id="scope_v1",
        quant_run_id="qr_test",
        decision_at=decision_at,
        include_near_threshold=False,
    )

    assert [target.security_id for target in targets] == ["000001.SZ"]
    assert targets[0].trigger_type == TargetTriggerType.QUANT_PASS
    assert targets[0].name == "平安银行"
    assert targets[0].industry_terms == ("银行",)


def test_quant_target_loader_can_include_near_threshold(
    target_repository: SQLAlchemyQuantNewsTargetRepository,
) -> None:
    """Explicit near-threshold mode includes PASS and near-threshold rows."""
    decision_at = datetime(2026, 6, 29, tzinfo=UTC)

    targets = target_repository.list_targets(
        scope_version_id="scope_v1",
        quant_run_id="qr_test",
        decision_at=decision_at,
        include_near_threshold=True,
    )

    assert [target.security_id for target in targets] == ["000001.SZ", "000002.SZ"]
    assert [target.trigger_type for target in targets] == [
        TargetTriggerType.QUANT_PASS,
        TargetTriggerType.NEAR_THRESHOLD,
    ]


def test_quant_target_loader_backfills_name_and_industry_from_company_pool(
    database_url: str,
) -> None:
    """Quant rows without names still produce company-aware news targets."""
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    decision_at = datetime(2026, 6, 29, tzinfo=UTC)
    with session_factory.begin() as session:
        session.add(
            DataSyncRunRow(
                run_id="dsr_company_pool",
                provider="tushare",
                status="completed",
                requested_by="test",
                endpoint_count=1,
                completed_count=1,
                failed_count=0,
                input_hash="sha256:data",
                request_payload={},
                started_at=decision_at,
                finished_at=decision_at,
                created_at=decision_at,
                error_summary={},
            )
        )
        session.add(
            SecurityMasterRow(
                security_id="002357.SZ",
                symbol="002357.SZ",
                name="富临运业",
                exchange="SZSE",
                listed_at=None,
                delisted_at=None,
                security_type="stock",
                system_from=decision_at,
                system_to=None,
                raw_lineage_ids=[],
            )
        )
        session.flush()
        session.add(
            CompanyPoolSnapshotRow(
                snapshot_id="cps_test",
                pool_code="all_a_non_st",
                source_run_id="dsr_company_pool",
                business_at=decision_at,
                known_at=decision_at,
                member_count=1,
                criteria={},
                input_hash="sha256:pool",
                created_at=decision_at,
            )
        )
        session.flush()
        session.add(
            CompanyPoolMemberRow(
                membership_id="cpm_test",
                snapshot_id="cps_test",
                security_id="002357.SZ",
                name="富临运业",
                exchange="SZSE",
                industry_code="transport",
                industry_name="道路运输",
                included=True,
                exclusion_reasons=[],
                data_status="ok",
            )
        )
        session.add(
            QuantScreenRunRow(
                quant_run_id="qr_missing_name",
                input_snapshot_id="qis_test",
                scope_version_id="scope_v1",
                strategy_version_id="strategy_v1",
                decision_at=decision_at,
                config_hash="sha256:config",
                status="completed",
                created_at=decision_at,
            )
        )
        session.add(
            QuantScreenResultRow(
                result_id="res_missing_name",
                quant_run_id="qr_missing_name",
                security_id="002357.SZ",
                final_score=80.0,
                screening_status="pass",
                data_status="valid",
                risk_flags=[],
                review_required=False,
                review_reasons=[],
                research_guardrail="research_allowed",
                reason_summary="seeded",
                factor_details={},
                created_at=decision_at,
            )
        )

    try:
        targets = SQLAlchemyQuantNewsTargetRepository(session_factory).list_targets(
            scope_version_id="scope_v1",
            quant_run_id="qr_missing_name",
            decision_at=decision_at,
            include_near_threshold=False,
        )

        assert len(targets) == 1
        assert targets[0].name == "富临运业"
        assert targets[0].symbol == "002357.SZ"
        assert targets[0].industry_terms == ("道路运输",)
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
