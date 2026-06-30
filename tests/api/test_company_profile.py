"""Company quant/analysis profile API endpoint tests."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient

from margin.api.main import create_app
from margin.settings import get_settings
from margin.valuation_discovery.analysis_mart import (
    AnalysisFinding,
    AnalysisMartBundle,
    AnalysisMetric,
    AnalysisSnapshot,
    MemoryAnalysisMartRepository,
)
from margin.valuation_discovery.models import (
    DataStatus,
    QuantResult,
    ResearchGuardrail,
    ScreeningStatus,
)
from margin.valuation_discovery.quant.repository import MemoryQuantRepository
from margin.valuation_discovery.service import CompanyProfileService

DECISION_AT = datetime(2026, 6, 24, 8, 0, tzinfo=UTC)
SECURITY_ID = "sec_001"
SCOPE_VERSION_ID = "scope_v1"


def _make_quant_result() -> QuantResult:
    """Build a quant result for API tests."""
    return QuantResult(
        result_id="qres_001",
        quant_run_id="qr_001",
        security_id=SECURITY_ID,
        final_score=82.5,
        quality_score=75.0,
        value_score=88.0,
        growth_score=60.0,
        momentum_score=70.0,
        risk_score=65.0,
        rank_overall=12,
        rank_in_industry=3,
        screening_status=ScreeningStatus.PASS,
        data_status=DataStatus.OK,
        risk_flags=("overheat",),
        review_required=False,
        review_reasons=(),
        research_guardrail=ResearchGuardrail.RESEARCH_ALLOWED,
        reason_summary="All factor groups above threshold.",
        factor_details={"pe_ttm": 12.3},
        created_at=DECISION_AT,
    )


def _make_analysis_snapshot() -> AnalysisSnapshot:
    """Build an analysis snapshot for API tests."""
    return AnalysisSnapshot(
        analysis_snapshot_id="ans_001",
        security_id=SECURITY_ID,
        scope_version_id=SCOPE_VERSION_ID,
        decision_at=DECISION_AT,
        trading_date=date(2026, 6, 24),
        analysis_version="v1",
        analysis_kind="quant_screen",
        quant_run_id="qr_001",
        quant_result_id="qres_001",
        input_snapshot_id=None,
        strategy_version_id=None,
        config_hash=None,
        input_hash="sha256:input",
        result_hash="sha256:result",
        summary={"headline": "Pass"},
    )


def _make_metric() -> AnalysisMetric:
    """Build a sample metric."""
    return AnalysisMetric(
        metric_id="am_001",
        analysis_snapshot_id="ans_001",
        metric_code="pe_ttm",
        metric_name="市盈率 TTM",
        metric_group="value",
        numeric_value=12.3,
        unit="x",
        direction="lower",
        percentile_market=85.2,
        percentile_industry=72.1,
        rank_market=120,
        rank_industry=8,
    )


def _make_finding() -> AnalysisFinding:
    """Build a sample finding."""
    return AnalysisFinding(
        finding_id="af_001",
        analysis_snapshot_id="ans_001",
        finding_type="value",
        severity="info",
        title="估值偏低",
        description="PE 低于行业中位数。",
        confidence=0.82,
        evidence_ids=("ev_001",),
    )


def _build_service(
    *,
    with_quant: bool = True,
    with_analysis: bool = True,
) -> CompanyProfileService:
    """Build a CompanyProfileService backed by in-memory repositories."""
    quant_repo = MemoryQuantRepository()
    analysis_repo = MemoryAnalysisMartRepository()
    if with_quant:
        quant_repo.add_results("qr_001", [_make_quant_result()])
    if with_analysis:
        from margin.valuation_discovery.analysis_mart import AnalysisEvidenceLink

        link = AnalysisEvidenceLink(
            link_id="ael_001",
            analysis_snapshot_id="ans_001",
            finding_id="af_001",
            metric_id="am_001",
            evidence_id="ev_001",
            source_type="evidence",
            source_id="ev_001",
            role="supporting",
        )
        analysis_repo.upsert_bundle(
            AnalysisMartBundle(
                snapshot=_make_analysis_snapshot(),
                metrics=(_make_metric(),),
                findings=(_make_finding(),),
                evidence_links=(link,),
            )
        )
    return CompanyProfileService(quant_repo, analysis_repo)


@pytest.fixture()
def api_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Return a TestClient with company profile service injected."""
    monkeypatch.setenv("MARGIN_ADMIN_API_TOKEN", "admin-test-token")
    monkeypatch.setenv("MARGIN_CSRF_TOKEN", "valid")
    get_settings.cache_clear()
    service = _build_service()
    app = create_app(company_profile_service=service)
    return TestClient(app)


def test_get_company_quant_profile_returns_200(api_client: TestClient) -> None:
    """Quant profile endpoint returns the five factor scores."""
    response = api_client.get(f"/api/v1/valuation-discovery/companies/{SECURITY_ID}/quant")

    assert response.status_code == 200
    body = response.json()
    assert body["security_id"] == SECURITY_ID
    assert body["final_score"] == 82.5
    assert body["rank_overall"] == 12
    assert body["rank_in_industry"] == 3
    assert body["screening_status"] == "pass"
    assert body["research_guardrail"] == "research_allowed"
    assert len(body["factor_scores"]) == 5
    quality = next(
        item for item in body["factor_scores"] if item["factor_key"] == "quality_score"
    )
    assert quality["score"] == 75.0
    assert quality["label"] == "质量"
    assert quality["weight"] == 0.35


def test_get_company_quant_profile_returns_404_for_unknown(api_client: TestClient) -> None:
    """Quant profile endpoint returns 404 when no result exists."""
    response = api_client.get("/api/v1/valuation-discovery/companies/unknown/quant")
    assert response.status_code == 404


def test_get_company_analysis_profile_returns_200(api_client: TestClient) -> None:
    """Analysis profile endpoint returns metrics and findings."""
    response = api_client.get(
        f"/api/v1/valuation-discovery/companies/{SECURITY_ID}/analysis",
        params={"scope_version_id": SCOPE_VERSION_ID},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["security_id"] == SECURITY_ID
    assert body["snapshot"] is not None
    assert body["snapshot"]["analysis_snapshot_id"] == "ans_001"
    assert len(body["metrics"]) == 1
    assert body["metrics"][0]["metric_code"] == "pe_ttm"
    assert body["metrics"][0]["percentile_market"] == 85.2
    assert len(body["findings"]) == 1
    assert body["findings"][0]["title"] == "估值偏低"
    assert body["evidence_link_count"] == 1


def test_get_company_analysis_profile_empty_when_no_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Analysis profile endpoint returns empty when no snapshot exists."""
    monkeypatch.setenv("MARGIN_ADMIN_API_TOKEN", "admin-test-token")
    monkeypatch.setenv("MARGIN_CSRF_TOKEN", "valid")
    get_settings.cache_clear()
    service = _build_service(with_analysis=False)
    app = create_app(company_profile_service=service)
    client = TestClient(app)

    response = client.get(
        f"/api/v1/valuation-discovery/companies/{SECURITY_ID}/analysis",
        params={"scope_version_id": SCOPE_VERSION_ID},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["snapshot"] is None
    assert body["metrics"] == []
    assert body["findings"] == []
    assert body["evidence_link_count"] == 0
