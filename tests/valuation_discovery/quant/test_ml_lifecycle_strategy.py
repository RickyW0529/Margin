"""ML lifecycle quant strategy tests."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from margin.valuation_discovery.models import (
    QuantInputSnapshot,
    ScreeningStatus,
)
from margin.valuation_discovery.quant.repository import MemoryQuantRepository
from margin.valuation_discovery.quant.service import QuantService

DECISION_AT = datetime(2026, 6, 30, 15, 0, tzinfo=UTC)


def test_ml_lifecycle_strategy_routes_from_snapshot_metadata() -> None:
    """The ML strategy family should produce ML metadata and 80% total stock weights.

    Returns:
        None: .
    """
    snapshot = _ml_snapshot(("strong.SZ", "steady.SZ", "overheated.SZ"))
    repository = MemoryQuantRepository()
    repository.set_cross_section(
        snapshot.snapshot_id,
        pd.DataFrame(
            [
                _row(
                    "strong.SZ",
                    revenue_yoy=0.42,
                    profit_yoy=0.36,
                    return_6m_ex_1m=0.18,
                    return_20d=0.08,
                    industry_lifecycle_score=92.0,
                    volatility_120d=0.23,
                    max_drawdown_250d=-0.10,
                ),
                _row(
                    "steady.SZ",
                    revenue_yoy=0.18,
                    profit_yoy=0.14,
                    return_6m_ex_1m=0.09,
                    return_20d=0.04,
                    industry_lifecycle_score=68.0,
                    volatility_120d=0.27,
                    max_drawdown_250d=-0.14,
                ),
                _row(
                    "overheated.SZ",
                    revenue_yoy=0.55,
                    profit_yoy=0.48,
                    return_6m_ex_1m=0.44,
                    return_20d=0.42,
                    industry_lifecycle_score=85.0,
                    volatility_120d=0.58,
                    max_drawdown_250d=-0.32,
                ),
            ]
        ).set_index("security_id", drop=False),
    )

    quant_run = QuantService(repository).run(snapshot, decision_at=DECISION_AT)

    results = repository.list_results(quant_run.quant_run_id)
    by_security = {item.security_id: item for item in results}
    strong = by_security["strong.SZ"]
    steady = by_security["steady.SZ"]
    overheated = by_security["overheated.SZ"]

    assert quant_run.strategy_version_id == "ml-lifecycle-v1"
    assert strong.factor_details["strategy_family"] == "ml_lgbm_lifecycle"
    assert strong.factor_details["ml_strategy"]["model_family"] == "lgbm_lifecycle"
    assert strong.factor_details["ml_strategy"]["profile_id"] == (
        "liquid-large-mid-lgbm-recent-trend80-ddstop-v1"
    )
    assert (
        strong.factor_details["ml_strategy"]["portfolio_construction"]["score_temperature"] == 0.2
    )
    assert strong.factor_details["ml_strategy"]["execution_boundary"] == ("research_only_no_order")
    assert strong.factor_details["ml_strategy"]["fallback_used"] is False
    assert strong.factor_details["ml_strategy"]["feature_coverage"]["coverage_ratio"] >= 0.7
    assert (
        strong.factor_details["ml_strategy"]["target_weight"]
        > steady.factor_details["ml_strategy"]["target_weight"]
    )
    assert sum(
        result.factor_details["ml_strategy"]["target_weight"] for result in results
    ) == pytest.approx(0.8)
    assert overheated.review_required is True
    assert "short_term_overheat" in overheated.review_reasons


def test_default_strategy_does_not_emit_ml_strategy_metadata() -> None:
    """The existing multi-factor path must stay compatible when no ML family is selected.

    Returns:
        None: .
    """
    snapshot = QuantInputSnapshot(
        snapshot_id="qis-default-strategy",
        scope_version_id="scope-v1",
        universe_snapshot_id="univ-snap-1",
        decision_at=DECISION_AT,
        known_at=DECISION_AT,
        security_ids=("000001.SZ",),
        required_indicators=("roe_ttm", "pe_ttm"),
    )
    repository = MemoryQuantRepository()
    repository.set_cross_section(
        snapshot.snapshot_id,
        pd.DataFrame([_row("000001.SZ")]).set_index("security_id", drop=False),
    )

    quant_run = QuantService(repository).run(snapshot, decision_at=DECISION_AT)

    result = repository.list_results(quant_run.quant_run_id)[0]
    assert result.screening_status in {
        ScreeningStatus.PASS,
        ScreeningStatus.NEAR_THRESHOLD,
        ScreeningStatus.WATCHLIST,
        ScreeningStatus.REJECT,
    }
    assert "ml_strategy" not in result.factor_details


def _ml_snapshot(security_ids: tuple[str, ...]) -> QuantInputSnapshot:
    """Helper ml_snapshot.

    Args:
        security_ids: tuple[str, ...]: .

    Returns:
        QuantInputSnapshot: .
    """
    return QuantInputSnapshot(
        snapshot_id="qis-ml-lifecycle",
        scope_version_id="scope-v1",
        universe_snapshot_id="univ-snap-1",
        decision_at=DECISION_AT,
        known_at=DECISION_AT,
        security_ids=security_ids,
        required_indicators=("roe_ttm", "pe_ttm"),
        quant_feature_set=SimpleNamespace(
            metadata={
                "quant_strategy": {
                    "quant_strategy_version_id": "ml-lifecycle-v1",
                    "strategy_family": "ml_lgbm_lifecycle",
                    "thresholds": {
                        "max_stock_exposure": 0.8,
                        "top_n": 3,
                        "pass_threshold": 70.0,
                        "near_threshold": 60.0,
                        "watch_threshold": 50.0,
                        "score_temperature": 0.2,
                        "min_cash": 0.2,
                        "exposure_mode": "trend80",
                        "daily_drawdown_stop": 0.10,
                    },
                }
            }
        ),
    )


def _row(
    security_id: str,
    *,
    revenue_yoy: float = 0.16,
    profit_yoy: float = 0.13,
    return_6m_ex_1m: float = 0.08,
    return_20d: float = 0.05,
    industry_lifecycle_score: float = 65.0,
    volatility_120d: float = 0.26,
    max_drawdown_250d: float = -0.14,
) -> dict[str, object]:
    """Helper row.

    Args:
        security_id: str: .
        revenue_yoy: float: .
        profit_yoy: float: .
        return_6m_ex_1m: float: .
        return_20d: float: .
        industry_lifecycle_score: float: .
        volatility_120d: float: .
        max_drawdown_250d: float: .

    Returns:
        dict[str, object]: .
    """
    return {
        "security_id": security_id,
        "name": security_id,
        "industry_id": "technology",
        "industry_family": "technology",
        "decision_at": DECISION_AT,
        "listing_date": datetime(2020, 1, 1, tzinfo=UTC),
        "is_st": False,
        "is_suspended": False,
        "avg_amount_20d": 200_000_000.0,
        "turnover_rate": 0.018,
        "volume_ratio": 1.05,
        "net_profit_y1": 100.0,
        "net_profit_y2": 90.0,
        "liability_ratio": 0.38,
        "goodwill_to_equity": 0.03,
        "ocf_to_net_profit": 1.05,
        "audit_opinion": "standard_unqualified",
        "net_profit_ttm": 120.0,
        "roe_ttm": 0.17,
        "roic_ttm": 0.14,
        "gross_margin_ttm": 0.36,
        "net_margin_ttm": 0.21,
        "interest_coverage": 9.0,
        "pe_ttm": 24.0,
        "pb": 2.5,
        "ps": 4.0,
        "dividend_yield": 0.01,
        "market_cap": 80_000_000_000.0,
        "revenue_yoy": revenue_yoy,
        "profit_yoy": profit_yoy,
        "return_20d": return_20d,
        "return_6m_ex_1m": return_6m_ex_1m,
        "return_12m_ex_1m": return_6m_ex_1m * 1.2,
        "index_relative_momentum": 0.04,
        "industry_relative_momentum": 0.03,
        "ma_trend": 0.06,
        "volatility_120d": volatility_120d,
        "max_drawdown_250d": max_drawdown_250d,
        "industry_lifecycle_score": industry_lifecycle_score,
    }
