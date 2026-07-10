"""Tests for complete document and warehouse-fact evidence details."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient

from margin.api.routes.evidence import get_evidence_detail_service, router
from margin.data.facts import StandardizedIndicatorFact
from margin.evidence.detail import (
    EvidenceDetailService,
    EvidenceSourceKind,
    QuantFactorEvidenceValue,
    QuantInputLineage,
    QuantResultEvidenceRecord,
    SQLAlchemyQuantResultDetailRepository,
)
from margin.evidence.models import Evidence
from margin.news.models import SourceLevel, make_document_event
from margin.storage.base import Base
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)
from margin.valuation_discovery.db_models import (
    QuantFactorValueRow,
    QuantInputSnapshotFactRow,
    QuantInputSnapshotRow,
    QuantScreenResultRow,
    QuantScreenRunRow,
)
from margin.valuation_discovery.models import (
    DataStatus,
    QuantInputSnapshot,
    QuantResult,
    QuantRun,
    ResearchGuardrail,
    ScreeningStatus,
)
from margin.valuation_discovery.quant.repository import SQLAlchemyQuantRepository
from margin.valuation_discovery.repository import SQLAlchemyValuationDiscoveryRepository


class MemoryEvidenceReader:
    def __init__(self, *items: Evidence) -> None:
        self.items = {item.evidence_id: item for item in items}

    def get_evidence(self, evidence_id: str) -> Evidence | None:
        return self.items.get(evidence_id)


class MemoryDocumentReader:
    def __init__(self, *items) -> None:  # noqa: ANN002
        self.by_event = {item.event_id: item for item in items}
        self.by_document = {item.document_id: item for item in items}

    def get_document_event(self, event_id: str):  # noqa: ANN201
        return self.by_event.get(event_id)

    def get_document_event_by_document_id(self, document_id: str):  # noqa: ANN201
        return self.by_document.get(document_id)


class MemoryFactReader:
    def __init__(self, *items: StandardizedIndicatorFact) -> None:
        self.items = {item.fact_id: item for item in items}

    def get_fact(self, fact_id: str) -> StandardizedIndicatorFact | None:
        return self.items.get(fact_id)


class MemoryQuantResultReader:
    def __init__(self, *items: QuantResultEvidenceRecord) -> None:
        self.items = {item.result.result_id: item for item in items}

    def get_quant_result(self, result_id: str) -> QuantResultEvidenceRecord | None:
        return self.items.get(result_id)


def _document_fixture():  # noqa: ANN202
    markdown = "# 公司财报\n\n需求大幅增长，供不应求。\n\n后续产能正在建设。"
    event = make_document_event(
        source_url="https://example.com/filing",
        source_name="szse",
        source_level=SourceLevel.L1,
        title="公司财报",
        content=markdown,
        doc_type="filing",
        document_id="doc_full",
        published_at=datetime(2026, 7, 1, tzinfo=UTC),
        available_at=datetime(2026, 7, 2, tzinfo=UTC),
        snapshot_id="snp_full",
    )
    quote = "需求大幅增长，供不应求。"
    start = markdown.index(quote)
    evidence = Evidence(
        evidence_id="ev_full",
        chunk_id="chk_full",
        document_id=event.document_id,
        source_type="filing_pdf",
        source_url=event.source_url,
        source_name=event.source_name,
        source_level=event.source_level,
        content_hash="sha256:chunk",
        content=quote,
        available_at=event.available_at,
        published_at=event.published_at,
        quote_span=(start, start + len(quote)),
        section="公司财报",
        snapshot_id=event.snapshot_id,
    )
    return event, evidence


def _fact_fixture() -> StandardizedIndicatorFact:
    timestamp = datetime(2026, 6, 30, tzinfo=UTC)
    return StandardizedIndicatorFact(
        fact_id="fact_roe_1",
        provider_code="tushare",
        provider_fact_id="provider_roe_1",
        endpoint_code="fina_indicator",
        security_id="000001.SZ",
        indicator_id="roe",
        indicator_version="v1",
        event_at=timestamp,
        available_at=timestamp,
        fetched_at=timestamp,
        numeric_value=Decimal("12.3400000000"),
        unit="%",
        quality_score=Decimal("0.99"),
        mapping_version="v1",
        raw_snapshot_id="raw_roe_1",
        lineage={"source_url": "warehouse://tushare/fina_indicator"},
    )


def _quant_fixture() -> QuantResultEvidenceRecord:
    timestamp = datetime(2026, 6, 30, 7, 0, tzinfo=UTC)
    quant_run = QuantRun(
        quant_run_id="qr_ml_1",
        input_snapshot_id="qis_ml_1",
        scope_version_id="scope_all_a_20260630",
        strategy_version_id="ml-lifecycle-v1",
        decision_at=timestamp,
        config_hash="sha256:quant-config",
        status="completed",
        created_at=timestamp,
    )
    result = QuantResult(
        result_id="qres_000001_ml_1",
        quant_run_id=quant_run.quant_run_id,
        security_id="000001.SZ",
        final_score=87.5,
        quality_score=82.0,
        value_score=76.5,
        growth_score=91.0,
        momentum_score=88.0,
        risk_score=35.0,
        rank_overall=3,
        rank_in_industry=1,
        screening_status=ScreeningStatus.PASS,
        data_status=DataStatus.OK,
        risk_flags=("估值波动",),
        review_required=True,
        review_reasons=("财报催化仍需复核",),
        research_guardrail=ResearchGuardrail.RESEARCH_ALLOWED,
        reason_summary="质量与成长因子共同驱动。",
        factor_details={
            "name": "平安银行",
            "ml_strategy": {
                "model_family": "lightgbm",
                "target_weight": 0.08,
            },
            "feature_coverage": {"coverage_ratio": 0.96},
        },
        created_at=timestamp,
    )
    return QuantResultEvidenceRecord(
        result=result,
        quant_run=quant_run,
        input_snapshot=QuantInputLineage(
            snapshot_id=quant_run.input_snapshot_id,
            scope_version_id=quant_run.scope_version_id,
            universe_snapshot_id="univ_snap_all_a_20260630",
            decision_at=timestamp,
            known_at=timestamp,
            required_indicators=("roe", "revenue_growth"),
            optional_indicators=("momentum_20d",),
            feature_snapshot_id="qfs_20260630",
            fact_count=2,
            data_status="ok",
            input_hash="sha256:quant-input",
        ),
        fact_ids=("fact_roe_1", "fact_revenue_growth_1"),
        factor_values=(
            QuantFactorEvidenceValue(
                factor_value_id="qfv_growth",
                factor_group="group_score",
                factor_name="growth",
                score=91.0,
                direction="higher",
                detail={"rank_in_industry": 1},
            ),
        ),
    )


def _service() -> EvidenceDetailService:
    event, evidence = _document_fixture()
    return EvidenceDetailService(
        evidence_reader=MemoryEvidenceReader(evidence),
        document_reader=MemoryDocumentReader(event),
        warehouse_fact_reader=MemoryFactReader(_fact_fixture()),
        quant_result_reader=MemoryQuantResultReader(_quant_fixture()),
    )


def test_document_evidence_returns_full_markdown_and_verified_highlight() -> None:
    event, evidence = _document_fixture()
    detail = _service().get_detail(evidence.evidence_id)

    assert detail is not None
    assert detail.source_kind == EvidenceSourceKind.DOCUMENT
    assert detail.markdown == event.content
    assert detail.markdown != evidence.content
    assert detail.highlights[0].quote == evidence.content
    highlighted = detail.markdown[detail.highlights[0].start : detail.highlights[0].end]
    assert highlighted == evidence.content
    assert detail.locator["quote_span"] == evidence.quote_span


def test_warehouse_fact_id_returns_markdown_locator_and_value_highlight() -> None:
    detail = _service().get_detail("fact_roe_1")

    assert detail is not None
    assert detail.source_kind == EvidenceSourceKind.WAREHOUSE_FACT
    assert "12.3400000000" in detail.markdown
    assert detail.highlights[0].quote == "12.3400000000"
    assert detail.locator["fact_id"] == "fact_roe_1"
    assert detail.locator["indicator_id"] == "roe"
    assert detail.snapshot_id == "raw_roe_1"


def test_warehouse_fact_multiline_value_uses_markdown_safe_separator() -> None:
    event, evidence = _document_fixture()
    multiline_fact = _fact_fixture().model_copy(
        update={"numeric_value": None, "text_value": "第一行\n第二行"}
    )
    service = EvidenceDetailService(
        evidence_reader=MemoryEvidenceReader(evidence),
        document_reader=MemoryDocumentReader(event),
        warehouse_fact_reader=MemoryFactReader(multiline_fact),
        quant_result_reader=MemoryQuantResultReader(_quant_fixture()),
    )

    detail = service.get_detail(multiline_fact.fact_id)

    assert detail is not None
    assert "第一行 / 第二行" in detail.markdown
    assert "<br>" not in detail.markdown
    assert detail.highlights[0].quote == "第一行 / 第二行"


def test_quant_result_id_returns_full_markdown_and_pit_lineage() -> None:
    quant = _quant_fixture()

    detail = _service().get_detail(quant.result.result_id)

    assert detail is not None
    assert detail.source_kind == EvidenceSourceKind.QUANT_RESULT
    assert detail.evidence_id == "qres_000001_ml_1"
    assert detail.snapshot_id == "qis_ml_1"
    assert detail.source_level == "L3"
    assert "## 分数组成" in detail.markdown
    assert "| 成长 | 91 |" in detail.markdown
    assert '"model_family": "lightgbm"' in detail.markdown
    assert "fact_revenue_growth_1" in detail.markdown
    assert detail.locator["quant_run_id"] == "qr_ml_1"
    assert detail.locator["input_snapshot_id"] == "qis_ml_1"
    assert detail.locator["fact_ids"] == ["fact_roe_1", "fact_revenue_growth_1"]
    assert detail.locator["lineage"]["fact_ids"] == detail.locator["fact_ids"]
    assert detail.pit_timestamp == quant.quant_run.decision_at
    assert detail.highlights[0].quote == "最终得分：87.5；筛选状态：pass"
    highlighted = detail.markdown[
        detail.highlights[0].start : detail.highlights[0].end
    ]
    assert highlighted == detail.highlights[0].quote


def test_sql_quant_detail_reader_resolves_persisted_result_lineage(
    database_url: str,
) -> None:
    quant = _quant_fixture()
    assert quant.quant_run is not None
    assert quant.input_snapshot is not None
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    _clear_quant_detail_fixture(session_factory)
    input_snapshot = QuantInputSnapshot(
        snapshot_id=quant.input_snapshot.snapshot_id,
        scope_version_id=quant.input_snapshot.scope_version_id,
        universe_snapshot_id=quant.input_snapshot.universe_snapshot_id,
        decision_at=quant.input_snapshot.decision_at,
        known_at=quant.input_snapshot.known_at,
        security_ids=("000001.SZ", "000002.SZ"),
        required_indicators=quant.input_snapshot.required_indicators,
        optional_indicators=quant.input_snapshot.optional_indicators,
        feature_snapshot_id=quant.input_snapshot.feature_snapshot_id,
        fact_refs=(
            {
                "fact_id": "fact_roe_1",
                "security_id": "000001.SZ",
                "indicator_id": "roe",
                "available_at": quant.input_snapshot.known_at,
                "payload_hash": "sha256:roe",
            },
            {
                "fact_id": "fact_revenue_growth_1",
                "security_id": "000001.SZ",
                "indicator_id": "revenue_growth",
                "available_at": quant.input_snapshot.known_at,
                "payload_hash": "sha256:revenue-growth",
            },
            {
                "fact_id": "fact_other_security",
                "security_id": "000002.SZ",
                "indicator_id": "roe",
                "available_at": quant.input_snapshot.known_at,
                "payload_hash": "sha256:other-security",
            },
        ),
        fact_count=3,
        data_status=DataStatus.OK,
    )
    try:
        SQLAlchemyValuationDiscoveryRepository(session_factory).add_quant_input_snapshot(
            input_snapshot
        )
        quant_repository = SQLAlchemyQuantRepository(session_factory)
        quant_repository.add_run(quant.quant_run)
        quant_repository.add_results(quant.quant_run.quant_run_id, (quant.result,))

        persisted = SQLAlchemyQuantResultDetailRepository(
            session_factory
        ).get_quant_result(quant.result.result_id)

        assert persisted is not None
        assert persisted.result.result_id == quant.result.result_id
        assert persisted.quant_run == quant.quant_run
        assert persisted.input_snapshot is not None
        assert persisted.input_snapshot.snapshot_id == "qis_ml_1"
        assert persisted.input_snapshot.fact_count == 3
        assert persisted.fact_ids == ("fact_revenue_growth_1", "fact_roe_1")
        assert "fact_other_security" not in persisted.fact_ids
        factor_by_name = {item.factor_name: item for item in persisted.factor_values}
        assert factor_by_name["growth"].score == 91.0
        assert factor_by_name["growth"].detail["rank_in_industry"] == 1
    finally:
        _clear_quant_detail_fixture(session_factory)
        engine.dispose()


def _clear_quant_detail_fixture(session_factory) -> None:  # noqa: ANN001
    with session_factory.begin() as session:
        session.query(QuantFactorValueRow).filter(
            QuantFactorValueRow.result_id == "qres_000001_ml_1"
        ).delete(synchronize_session=False)
        session.query(QuantScreenResultRow).filter(
            QuantScreenResultRow.result_id == "qres_000001_ml_1"
        ).delete(synchronize_session=False)
        session.query(QuantScreenRunRow).filter(
            QuantScreenRunRow.quant_run_id == "qr_ml_1"
        ).delete(synchronize_session=False)
        session.query(QuantInputSnapshotFactRow).filter(
            QuantInputSnapshotFactRow.snapshot_id == "qis_ml_1"
        ).delete(synchronize_session=False)
        session.query(QuantInputSnapshotRow).filter(
            QuantInputSnapshotRow.snapshot_id == "qis_ml_1"
        ).delete(synchronize_session=False)


def test_evidence_detail_api_contract_and_not_found() -> None:
    application = FastAPI()
    application.include_router(router)
    application.dependency_overrides[get_evidence_detail_service] = _service

    with TestClient(application) as client:
        response = client.get("/api/v1/evidence/ev_full")
        quant_response = client.get("/api/v1/evidence/qres_000001_ml_1")
        missing = client.get("/api/v1/evidence/missing")

    assert response.status_code == 200
    payload = response.json()
    assert payload["evidence_id"] == "ev_full"
    assert payload["source_kind"] == "document"
    assert payload["document_id"] == "doc_full"
    assert payload["highlights"][0]["label"] == "公司财报"
    assert quant_response.status_code == 200
    quant_payload = quant_response.json()
    assert quant_payload["source_kind"] == "quant_result"
    assert quant_payload["locator"]["quant_run_id"] == "qr_ml_1"
    assert quant_payload["locator"]["input_snapshot_id"] == "qis_ml_1"
    assert quant_payload["locator"]["fact_ids"] == [
        "fact_roe_1",
        "fact_revenue_growth_1",
    ]
    assert missing.status_code == 404
