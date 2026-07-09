"""Factor scoring and selector tests.

This module validates value scoring, group weight combination, selector
inclusion rules, status decisions, and quant service persistence and ranking.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from margin.valuation_discovery.models import (
    DataStatus,
    QuantInputSnapshot,
    QuantResult,
    ResearchGuardrail,
    ScreeningStatus,
)
from margin.valuation_discovery.quant.repository import MemoryQuantRepository
from margin.valuation_discovery.quant.scoring import FactorGroupScores, FactorScorer
from margin.valuation_discovery.quant.selector import MultiFactorSelector, SelectorConfig
from margin.valuation_discovery.quant.service import QuantService


def test_negative_pe_does_not_get_high_value_score() -> None:
    """Verify a negative PE does not receive a high value score.

    Returns:
        None: .
    """
    frame = pd.DataFrame(
        {
            "security_id": ["loss", "profit"],
            "industry_id": ["tech", "tech"],
            "pe_ttm": [-5.0, 20.0],
            "pb": [1.0, 1.2],
            "fcf_yield": [0.01, 0.04],
        }
    )

    result = FactorScorer().score_value(frame)

    assert result.loc[result.security_id == "loss", "pe_score"].iloc[0] == 0.0


def test_final_score_uses_configured_group_weights() -> None:
    """Verify the final score uses configured factor group weights.

    Returns:
        None: .
    """
    result = FactorScorer().combine(
        FactorGroupScores(
            security_id="000001.SZ",
            quality_score=80,
            value_score=70,
            growth_score=60,
            momentum_score=50,
            risk_score=90,
        )
    )

    expected = 0.35 * 80 + 0.25 * 70 + 0.15 * 60 + 0.15 * 50 + 0.10 * 90
    assert result.final_score == expected


def test_selector_includes_pass_and_near_threshold_without_block_buy() -> None:
    """Verify the selector includes pass and near-threshold results without block-buy.
    Returns:.

    Returns:
        None: .
    """
    results = (
        QuantResult(
            quant_run_id="qr-1",
            security_id="pass",
            final_score=85,
            screening_status=ScreeningStatus.PASS,
            research_guardrail=ResearchGuardrail.RESEARCH_ALLOWED,
        ),
        QuantResult(
            quant_run_id="qr-1",
            security_id="near",
            final_score=75,
            screening_status=ScreeningStatus.NEAR_THRESHOLD,
            research_guardrail=ResearchGuardrail.LIMITED_RESEARCH,
        ),
        QuantResult(
            quant_run_id="qr-1",
            security_id="blocked",
            final_score=90,
            screening_status=ScreeningStatus.PASS,
            research_guardrail=ResearchGuardrail.RESEARCH_BLOCKED,
        ),
    )

    selected = MultiFactorSelector(SelectorConfig(top_n=10, min_score=70)).select(results)

    assert [item.security_id for item in selected] == ["pass", "near"]


def test_status_decider_prevents_low_quality_pass() -> None:
    """Verify the status decider prevents a low-quality result from passing.

    Returns:
        None: .
    """
    combined = FactorScorer().combine(
        FactorGroupScores(
            security_id="000001.SZ",
            quality_score=45,
            value_score=100,
            growth_score=100,
            momentum_score=100,
            risk_score=90,
        )
    )

    decision = FactorScorer().determine_status(
        combined,
        data_status=DataStatus.OK,
        risk_flags=(),
        short_term_overheat=False,
    )

    assert decision.screening_status != ScreeningStatus.PASS
    assert decision.research_guardrail == ResearchGuardrail.CONFIDENCE_REDUCED


def test_quant_service_rejects_invalid_input_snapshot() -> None:
    """Verify the quant service rejects an input snapshot with missing required indicators.

    Returns:
        None: .
    """
    snapshot = QuantInputSnapshot(
        snapshot_id="qis-invalid",
        scope_version_id="scope-v1",
        universe_snapshot_id="univ-snap-1",
        decision_at=datetime(2026, 6, 22, tzinfo=UTC),
        known_at=datetime(2026, 6, 22, tzinfo=UTC),
        security_ids=("000001.SZ",),
        required_indicators=("roe_ttm",),
        missing_required=("roe_ttm",),
    )

    service = QuantService(MemoryQuantRepository())

    with pytest.raises(ValueError, match="invalid quant input snapshot"):
        service.run(snapshot, decision_at=datetime(2026, 6, 22, tzinfo=UTC))


def test_filtered_companies_are_still_persisted() -> None:
    """Verify filtered companies are still persisted with reject status and reasons.

    Returns:
        None: .
    """
    snapshot = QuantInputSnapshot(
        snapshot_id="qis-valid",
        scope_version_id="scope-v1",
        universe_snapshot_id="univ-snap-1",
        decision_at=datetime(2026, 6, 22, tzinfo=UTC),
        known_at=datetime(2026, 6, 22, tzinfo=UTC),
        security_ids=("000001.SZ", "000002.SZ"),
        required_indicators=("roe_ttm", "pe_ttm"),
    )
    repository = MemoryQuantRepository()
    repository.set_cross_section(
        snapshot.snapshot_id,
        pd.DataFrame(
            [
                _quant_row("000001.SZ", is_st=False),
                _quant_row("000002.SZ", is_st=True),
            ]
        ).set_index("security_id", drop=False),
    )

    quant_run = QuantService(repository).run(
        snapshot,
        decision_at=datetime(2026, 6, 22, tzinfo=UTC),
    )

    results = repository.list_results(quant_run.quant_run_id)
    assert {result.security_id for result in results} == {"000001.SZ", "000002.SZ"}
    assert any(result.screening_status == ScreeningStatus.REJECT for result in results)
    assert all(result.reason_summary for result in results)


def test_quant_service_assigns_overall_and_industry_ranks() -> None:
    """Verify the quant service assigns overall and industry ranks to results.

    Returns:
        None: .
    """
    snapshot = QuantInputSnapshot(
        snapshot_id="qis-ranks",
        scope_version_id="scope-v1",
        universe_snapshot_id="univ-snap-1",
        decision_at=datetime(2026, 6, 22, tzinfo=UTC),
        known_at=datetime(2026, 6, 22, tzinfo=UTC),
        security_ids=("000001.SZ", "000002.SZ"),
        required_indicators=("roe_ttm", "pe_ttm"),
    )
    strong = _quant_row("000001.SZ", is_st=False)
    weak = _quant_row("000002.SZ", is_st=False)
    weak.update(
        {
            "roe_ttm": 0.03,
            "roic_ttm": 0.02,
            "gross_margin_ttm": 0.12,
            "net_margin_ttm": 0.04,
            "ocf_to_net_profit": 0.70,
            "pe_ttm": 35.0,
            "pb": 3.0,
            "fcf_yield": 0.005,
            "growth_score": 30.0,
            "momentum_score": 25.0,
            "risk_score": 45.0,
        }
    )
    repository = MemoryQuantRepository()
    repository.set_cross_section(
        snapshot.snapshot_id,
        pd.DataFrame([strong, weak]).set_index("security_id", drop=False),
    )

    quant_run = QuantService(repository).run(
        snapshot,
        decision_at=datetime(2026, 6, 22, tzinfo=UTC),
    )

    results = repository.list_results(quant_run.quant_run_id)
    by_security = {result.security_id: result for result in results}
    assert by_security["000001.SZ"].rank_overall == 1
    assert by_security["000001.SZ"].rank_in_industry == 1
    profile = by_security["000001.SZ"].factor_details["ai_quant_profile"]
    assert profile["strategy_profile"] == "manual_all_a_no_market_cap_no_top_n"
    assert profile["execution_boundary"] == "research_only_no_order"
    assert profile["scores"]["manual_all_a_score"] is not None
    assert by_security["000002.SZ"].rank_overall == 2
    assert by_security["000002.SZ"].rank_in_industry == 2


def test_quant_service_final_score_uses_confirmed_theme_hotness() -> None:
    """Verify confirmed theme hotness changes real quant score, rank, and status.

    Returns:
        None: .
    """
    theme_only_weights = {
        "value": 0.0,
        "dividend": 0.0,
        "reversal": 0.0,
        "liquidity": 0.0,
        "volume_sentiment": 0.0,
        "momentum": 0.0,
        "risk_health": 0.0,
        "theme_hotness": 1.0,
    }
    snapshot = QuantInputSnapshot(
        snapshot_id="qis-theme-hotness",
        scope_version_id="scope-v1",
        universe_snapshot_id="univ-snap-1",
        decision_at=datetime(2026, 6, 22, tzinfo=UTC),
        known_at=datetime(2026, 6, 22, tzinfo=UTC),
        security_ids=("theme.SZ", "plain.SZ"),
        required_indicators=("roe_ttm", "pe_ttm"),
        quant_feature_set=SimpleNamespace(
            metadata={
                "quant_strategy": {
                    "quant_strategy_version_id": "theme-hotness-v1",
                    "thresholds": {
                        "default_universe": "ALL_A",
                        "presets": {
                            "ALL_A": {
                                "buy_threshold": 70.0,
                                "min_avg_amount_20d": 1.0,
                                "factor_weights": theme_only_weights,
                            }
                        },
                    },
                }
            }
        ),
    )
    themed = _quant_row("theme.SZ", is_st=False)
    themed.update(
        {
            "theme_hot_score": 85.0,
            "theme_member_confidence": 1.0,
            "theme_signal_confirmed": True,
        }
    )
    plain = _quant_row("plain.SZ", is_st=False)
    repository = MemoryQuantRepository()
    repository.set_cross_section(
        snapshot.snapshot_id,
        pd.DataFrame([themed, plain]).set_index("security_id", drop=False),
    )

    quant_run = QuantService(repository).run(
        snapshot,
        decision_at=datetime(2026, 6, 22, tzinfo=UTC),
    )

    by_security = {
        result.security_id: result for result in repository.list_results(quant_run.quant_run_id)
    }
    assert by_security["theme.SZ"].final_score == pytest.approx(85.0)
    assert by_security["plain.SZ"].final_score == pytest.approx(0.0)
    assert by_security["theme.SZ"].rank_overall == 1
    assert by_security["plain.SZ"].screening_status == ScreeningStatus.REJECT
    assert by_security["theme.SZ"].screening_status == ScreeningStatus.PASS
    assert by_security["theme.SZ"].factor_details["scores"]["theme_hotness"] == pytest.approx(85.0)


def _quant_row(security_id: str, *, is_st: bool) -> dict[str, object]:
    """Build one deterministic quant cross-section row for scoring tests.

    Args:
        security_id: str: .
        is_st: bool: .

    Returns:
        dict[str, object]: .
    """
    return {
        "security_id": security_id,
        "industry_id": "bank",
        "industry_family": "financial",
        "decision_at": datetime(2026, 6, 22, tzinfo=UTC),
        "listing_date": datetime(2020, 1, 1, tzinfo=UTC),
        "is_st": is_st,
        "is_suspended": False,
        "avg_amount_20d": 80_000_000.0,
        "net_profit_y1": 100.0,
        "net_profit_y2": 90.0,
        "liability_ratio": 0.40,
        "goodwill_to_equity": 0.02,
        "ocf_to_net_profit": 1.1,
        "audit_opinion": "standard_unqualified",
        "net_profit_ttm": 120.0,
        "roe_ttm": 0.15,
        "roic_ttm": 0.12,
        "gross_margin_ttm": 0.35,
        "net_margin_ttm": 0.20,
        "interest_coverage": 8.0,
        "pe_ttm": 12.0,
        "pb": 1.1,
        "fcf_yield": 0.04,
        "growth_score": 70.0,
        "momentum_score": 65.0,
        "risk_score": 80.0,
    }
