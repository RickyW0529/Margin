"""Contracts for the independent quant, catalyst, and fusion workers."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from margin.agents.workers.recommendation_workers import (
    CatalystCandidate,
    CatalystResearchContext,
    EarningsCatalystWorker,
    EarningsCatalystWorkerResult,
    MemoryRecommendationArtifactRepository,
    MLQuantWorker,
    MLQuantWorkerResult,
    QuantRecommendationCandidate,
    RecommendationEvidenceRef,
    RecommendationFusionWorker,
)
from margin.valuation_discovery.models import (
    DataStatus,
    QuantResult,
    ResearchGuardrail,
    ScreeningStatus,
)

DECISION_AT = datetime(2026, 6, 22, tzinfo=UTC)


def test_ml_quant_worker_consumes_frozen_profile_and_persists_passed_weights() -> None:
    repository = MemoryRecommendationArtifactRepository()
    quant_service = _QuantService()
    worker = MLQuantWorker(quant_service=quant_service, repository=repository)
    profile = {
        "profile_id": "profile-v2",
        "model_family": "deterministic_weighted_signal",
        "implementation": "deterministic_weighted_signal_formula_v1",
        "quant_strategy": {
            "quant_strategy_version_id": "weighted-v2",
            "strategy_family": "deterministic_weighted_signal_lifecycle",
            "model_family": "deterministic_weighted_signal",
            "implementation": "deterministic_weighted_signal_formula_v1",
            "thresholds": {"max_stock_exposure": 0.75, "min_cash": 0.25},
        },
    }

    result = worker.run(
        orchestration_run_id="run-1",
        scope_version_id="scope-1",
        decision_at=DECISION_AT,
        input_snapshot="snapshot-1",
        profile=profile,
    )

    assert quant_service.strategy_metadata == profile["quant_strategy"]
    assert result.model_family == "deterministic_weighted_signal"
    assert result.implementation == "deterministic_weighted_signal_formula_v1"
    assert "lgbm" not in result.model_family.lower()
    assert result.max_stock_exposure == 0.75
    assert [candidate.security_id for candidate in result.candidates] == ["000001.SZ"]
    assert result.candidates[0].target_weight == 0.75
    assert worker.load(result.artifact_id) == result


def test_earnings_catalyst_worker_skips_outside_window_without_new_filing() -> None:
    review_service = _ReviewService()
    websearch = _WebSearch()
    worker = EarningsCatalystWorker(
        review_service=review_service,
        repository=MemoryRecommendationArtifactRepository(),
        context_loader=lambda _ids: (
            CatalystResearchContext(
                context_snapshot_id="ctx-1",
                security_id="000001.SZ",
                previous_conclusion="需求持续增长",
                new_filing_document_ids=("filing-off-season",),
            ),
        ),
        websearch_provider=websearch,
    )

    result = worker.run(
        orchestration_run_id="run-1",
        scope_version_id="scope-1",
        decision_at=DECISION_AT,
        context_snapshot_ids=("ctx-1",),
    )

    assert result.status == "skipped_outside_reporting_window"
    assert review_service.calls == 0
    assert websearch.queries == []


def test_new_rag_filing_triggers_review_and_counter_evidence_search() -> None:
    review = SimpleNamespace(
        conclusion="需求仍处于扩张阶段",
        confidence=0.8,
        outcome=SimpleNamespace(value="update_assessment"),
        valuation_view="positive",
        evidence_ids=("ev-rag-1",),
    )
    websearch = _WebSearch(
        results=[
            {
                "url": "https://example.com/counter",
                "title": "公司订单不及预期",
                "snippet": "下游需求下降，存在取消订单风险。",
            }
        ]
    )
    worker = EarningsCatalystWorker(
        review_service=_ReviewService(),
        repository=MemoryRecommendationArtifactRepository(),
        context_loader=lambda _ids: (
            CatalystResearchContext(
                context_snapshot_id="ctx-1",
                security_id="000001.SZ",
                previous_conclusion="订单供不应求，需求持续增长",
                evidence_ids=("ev-rag-1",),
                new_filing_document_ids=("filing-1",),
            ),
        ),
        review_loader=lambda _review_id: review,
        websearch_provider=websearch,
    )

    result = worker.run(
        orchestration_run_id="run-1",
        scope_version_id="scope-1",
        decision_at=datetime(2026, 7, 15, tzinfo=UTC),
        context_snapshot_ids=("ctx-1",),
    )

    assert result.status == "completed"
    assert result.trigger_reasons == (
        "financial_reporting_window",
        "new_rag_filing_ingested",
    )
    assert result.candidates[0].direction == "negative"
    assert result.candidates[0].contradiction_status == "counter_evidence_found"
    assert {item.source_type for item in result.candidates[0].evidence} == {
        "rag",
        "websearch",
    }
    assert len(websearch.queries) == 1


def test_fusion_applies_risk_gate_normalizes_stock_exposure_and_keeps_cash() -> None:
    repository = MemoryRecommendationArtifactRepository()
    fusion = RecommendationFusionWorker(repository=repository)
    quant_result = MLQuantWorkerResult(
        artifact_id="ml-1",
        orchestration_run_id="run-1",
        quant_run_id="quant-1",
        profile_id="profile-1",
        strategy_family="deterministic_weighted_signal_lifecycle",
        model_family="deterministic_weighted_signal",
        implementation="deterministic_weighted_signal_formula_v1",
        max_stock_exposure=0.8,
        min_cash=0.2,
        candidates=(
            _candidate("000001.SZ", 0.45, risk_flags=("high_leverage",)),
            _candidate("000002.SZ", 0.35, risk_flags=("short_term_overheat",)),
        ),
    )
    catalyst_result = EarningsCatalystWorkerResult(
        artifact_id="cat-1",
        orchestration_run_id="run-1",
        status="completed",
        candidates=(
            CatalystCandidate(
                security_id="000001.SZ",
                context_snapshot_id="ctx-1",
                direction="positive",
                confidence=0.8,
                reasons=("rag_delta_review_completed",),
                evidence=(RecommendationEvidenceRef(source_type="rag", source_id="ev-1"),),
            ),
            CatalystCandidate(
                security_id="000003.SZ",
                context_snapshot_id="ctx-3",
                direction="positive",
                confidence=0.9,
                conclusion="新财报显示供不应求与盈利加速",
                reasons=("new_filing_reviewed_from_rag",),
                evidence=(RecommendationEvidenceRef(source_type="rag", source_id="ev-3"),),
            ),
        ),
    )

    result = fusion.run(
        orchestration_run_id="run-1",
        scope_version_id="scope-1",
        decision_at=DECISION_AT,
        quant_result=quant_result,
        catalyst_result=catalyst_result,
    )

    assert result.excluded_security_ids == ("000002.SZ",)
    assert result.stock_weight == pytest.approx(0.8)
    assert result.cash_weight == pytest.approx(0.2)
    by_security = {item.security_id: item for item in result.recommendations}
    assert by_security["000001.SZ"].sources == ("ml_quant", "earnings_catalyst")
    assert by_security["000001.SZ"].quant_score == 80.0
    assert by_security["000001.SZ"].fusion_confidence == pytest.approx(0.90)
    assert by_security["000001.SZ"].risk_flags == ("high_leverage",)
    assert by_security["000001.SZ"].adjusted_weight == pytest.approx(0.78)
    assert by_security["000003.SZ"].sources == ("earnings_catalyst",)
    assert by_security["000003.SZ"].quant_score is None
    assert by_security["000003.SZ"].fusion_confidence == 0.9
    assert by_security["000003.SZ"].quant_contribution == 0.0
    assert by_security["000003.SZ"].adjusted_weight == pytest.approx(0.02)
    assert result.policy.catalyst_only_max_weight == 0.02
    assert fusion.load(result.artifact_id) == result


class _QuantService:
    def __init__(self) -> None:
        self.strategy_metadata: dict | None = None

    def run(self, **kwargs: object) -> object:
        self.strategy_metadata = kwargs["strategy_metadata"]  # type: ignore[assignment]
        return SimpleNamespace(
            quant_run_id="quant-1",
            results=(
                QuantResult(
                    result_id="qres-1",
                    quant_run_id="quant-1",
                    security_id="000001.SZ",
                    final_score=82.0,
                    screening_status=ScreeningStatus.PASS,
                    data_status=DataStatus.OK,
                    research_guardrail=ResearchGuardrail.RESEARCH_ALLOWED,
                    reason_summary="weighted signal passed",
                    factor_details={"ml_strategy": {"target_weight": 0.75}},
                ),
            ),
        )


class _ReviewService:
    def __init__(self) -> None:
        self.calls = 0

    def review(self, **_kwargs: object) -> object:
        self.calls += 1
        return SimpleNamespace(review_ids=("review-1",))


class _WebSearch:
    def __init__(self, results: list[dict[str, str]] | None = None) -> None:
        self.results = list(results or [])
        self.queries: list[str] = []

    def search(self, query: str, max_results: int = 5) -> list[dict[str, str]]:
        self.queries.append(query)
        return self.results[:max_results]


def _candidate(
    security_id: str,
    target_weight: float,
    *,
    risk_flags: tuple[str, ...] = (),
) -> QuantRecommendationCandidate:
    return QuantRecommendationCandidate(
        security_id=security_id,
        quant_result_id=f"qres-{security_id}",
        score=80.0,
        screening_status="pass",
        target_weight=target_weight,
        risk_flags=risk_flags,
        reasons=("quant_passed",),
    )
