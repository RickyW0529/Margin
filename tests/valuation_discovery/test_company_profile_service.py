"""Company quant/analysis profile service unit tests.

Validates the read-only CompanyProfileService that backs the company
visualization endpoints, using in-memory quant and Analysis Mart repositories.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

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


def _make_quant_result(
    *,
    security_id: str = SECURITY_ID,
    final_score: float = 82.5,
    quality: float = 75.0,
    value: float = 88.0,
    growth: float = 60.0,
    momentum: float = 70.0,
    risk: float = 65.0,
    screening_status: ScreeningStatus = ScreeningStatus.PASS,
    quant_run_id: str = "qr_001",
    result_id: str = "qres_001",
    created_at: datetime = DECISION_AT,
) -> QuantResult:
    """Build a quant result with five factor scores.

    Args:
        security_id: str: .
        final_score: float: .
        quality: float: .
        value: float: .
        growth: float: .
        momentum: float: .
        risk: float: .
        screening_status: ScreeningStatus: .
        quant_run_id: str: .
        result_id: str: .
        created_at: datetime: .

    Returns:
        QuantResult: .
    """
    return QuantResult(
        result_id=result_id,
        quant_run_id=quant_run_id,
        security_id=security_id,
        final_score=final_score,
        quality_score=quality,
        value_score=value,
        growth_score=growth,
        momentum_score=momentum,
        risk_score=risk,
        rank_overall=12,
        rank_in_industry=3,
        screening_status=screening_status,
        data_status=DataStatus.OK,
        risk_flags=("overheat",),
        review_required=False,
        review_reasons=(),
        research_guardrail=ResearchGuardrail.RESEARCH_ALLOWED,
        reason_summary="All factor groups above threshold.",
        factor_details={"pe_ttm": 12.3},
        created_at=created_at,
    )


def _make_analysis_snapshot() -> AnalysisSnapshot:
    """Build a minimal analysis snapshot.

    Returns:
        AnalysisSnapshot: .
    """
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
        summary={"headline": "Pass with strong value"},
    )


def _make_metric() -> AnalysisMetric:
    """Build a sample analysis metric.

    Returns:
        AnalysisMetric: .
    """
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
    """Build a sample analysis finding.

    Returns:
        AnalysisFinding: .
    """
    return AnalysisFinding(
        finding_id="af_001",
        analysis_snapshot_id="ans_001",
        finding_type="value",
        severity="info",
        title="估值偏低",
        description="PE 低于行业中位数的 72 分位。",
        confidence=0.82,
        evidence_ids=("ev_001",),
    )


def test_get_quant_profile_returns_five_factor_scores() -> None:
    """Quant profile should expose all five factor scores with labels/weights.

    Returns:
        None: .
    """
    quant_repo = MemoryQuantRepository()
    analysis_repo = MemoryAnalysisMartRepository()
    quant_repo.add_results("qr_001", [_make_quant_result()])
    service = CompanyProfileService(quant_repo, analysis_repo)

    profile = service.get_quant_profile(SECURITY_ID)

    assert profile is not None
    assert profile.security_id == SECURITY_ID
    assert profile.final_score == 82.5
    assert profile.rank_overall == 12
    assert profile.rank_in_industry == 3
    assert profile.screening_status == "pass"
    assert profile.research_guardrail == "research_allowed"
    assert len(profile.factor_scores) == 5
    keys = [item.factor_key for item in profile.factor_scores]
    assert keys == [
        "quality_score",
        "value_score",
        "growth_score",
        "momentum_score",
        "risk_score",
    ]
    quality = next(item for item in profile.factor_scores if item.factor_key == "quality_score")
    assert quality.score == 75.0
    assert quality.label == "质量"
    assert quality.weight == 0.35
    value = next(item for item in profile.factor_scores if item.factor_key == "value_score")
    assert value.weight == 0.25


def test_get_quant_profile_returns_none_for_unknown_security() -> None:
    """Quant profile should return None when no result exists.

    Returns:
        None: .
    """
    quant_repo = MemoryQuantRepository()
    analysis_repo = MemoryAnalysisMartRepository()
    service = CompanyProfileService(quant_repo, analysis_repo)

    assert service.get_quant_profile("unknown") is None


def test_get_quant_profile_picks_latest_result() -> None:
    """Quant profile should return the most recent result for a security.

    Returns:
        None: .
    """
    quant_repo = MemoryQuantRepository()
    analysis_repo = MemoryAnalysisMartRepository()
    earlier = _make_quant_result(final_score=70.0)
    later = _make_quant_result(
        final_score=85.0,
        quant_run_id="qr_002",
        result_id="qres_002",
        created_at=datetime(2026, 6, 25, 8, 0, tzinfo=UTC),
    )
    quant_repo.add_results("qr_001", (earlier,))
    quant_repo.add_results("qr_002", (later,))
    service = CompanyProfileService(quant_repo, analysis_repo)

    profile = service.get_quant_profile(SECURITY_ID)
    assert profile is not None
    assert profile.final_score == 85.0


def test_get_analysis_profile_returns_metrics_and_findings() -> None:
    """Analysis profile should expose metrics, findings, and link count.

    Returns:
        None: .
    """
    quant_repo = MemoryQuantRepository()
    analysis_repo = MemoryAnalysisMartRepository()
    snapshot = _make_analysis_snapshot()
    metric = _make_metric()
    finding = _make_finding()
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
            snapshot=snapshot,
            metrics=(metric,),
            findings=(finding,),
            evidence_links=(link,),
        )
    )
    service = CompanyProfileService(quant_repo, analysis_repo)

    profile = service.get_analysis_profile(SECURITY_ID, SCOPE_VERSION_ID)

    assert profile.security_id == SECURITY_ID
    assert profile.analysis_snapshot is not None
    assert profile.analysis_snapshot.analysis_snapshot_id == "ans_001"
    assert len(profile.metrics) == 1
    assert profile.metrics[0].metric_code == "pe_ttm"
    assert profile.metrics[0].percentile_market == 85.2
    assert len(profile.findings) == 1
    assert profile.findings[0].title == "估值偏低"
    assert profile.evidence_link_count == 1


def test_get_analysis_profile_returns_empty_when_no_snapshot() -> None:
    """Analysis profile should return empty metrics/findings when no snapshot.

    Returns:
        None: .
    """
    quant_repo = MemoryQuantRepository()
    analysis_repo = MemoryAnalysisMartRepository()
    service = CompanyProfileService(quant_repo, analysis_repo)

    profile = service.get_analysis_profile(SECURITY_ID, SCOPE_VERSION_ID)

    assert profile.security_id == SECURITY_ID
    assert profile.analysis_snapshot is None
    assert profile.metrics == ()
    assert profile.findings == ()
    assert profile.evidence_link_count == 0
