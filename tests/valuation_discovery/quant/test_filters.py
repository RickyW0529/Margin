"""Hard filter tests for valuation discovery quant.

This module validates that the hard filter engine rejects ST stocks with
structured reasons, retains low-liquidity companies with warnings, and
marks missing critical financials as data-insufficient.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from margin.valuation_discovery.models import DataStatus
from margin.valuation_discovery.quant.config import QuantConfig
from margin.valuation_discovery.quant.filters import HardFilterEngine


@pytest.fixture
def quant_frame() -> pd.DataFrame:
    """Return a deterministic single-row quant cross-section DataFrame.

    Returns:
        A pandas DataFrame indexed by security_id with one valid company row.
    """
    frame = pd.DataFrame(
        [
            {
                "security_id": "000001.SZ",
                "is_st": False,
                "is_suspended": False,
                "listing_date": datetime(2020, 1, 1, tzinfo=UTC),
                "decision_at": datetime(2026, 6, 22, tzinfo=UTC),
                "avg_amount_20d": 80_000_000,
                "net_profit_ttm": 1_000_000_000,
                "net_profit_y1": 900_000_000,
                "net_profit_y2": 800_000_000,
                "liability_ratio": 0.40,
                "industry_family": "industrial",
                "goodwill_to_equity": 0.05,
                "ocf_to_net_profit": 1.10,
                "audit_opinion": "standard_unqualified",
            }
        ]
    ).set_index("security_id", drop=False)
    return frame


def test_st_stock_is_rejected_with_structured_reason(quant_frame: pd.DataFrame) -> None:
    """Verify an ST stock is rejected with a structured blocker reason.

    Args:
        quant_frame: Deterministic quant cross-section DataFrame fixture.

    Returns:
        None.
    """
    quant_frame.loc["000001.SZ", "is_st"] = True
    result = HardFilterEngine(QuantConfig()).apply(quant_frame)

    rejected = result.by_security["000001.SZ"]
    assert rejected.allowed_for_scoring is False
    assert rejected.reasons[0].code == "st_stock"
    assert rejected.reasons[0].severity == "blocker"


def test_low_turnover_keeps_company_in_result_with_reason(quant_frame: pd.DataFrame) -> None:
    """Verify low turnover keeps the company in results with a structured reason.

    Args:
        quant_frame: Deterministic quant cross-section DataFrame fixture.

    Returns:
        None.
    """
    quant_frame.loc["000001.SZ", "avg_amount_20d"] = 10_000_000
    result = HardFilterEngine(QuantConfig(min_avg_amount_20d=50_000_000)).apply(quant_frame)

    reason = result.by_security["000001.SZ"].reason_by_code("low_liquidity")
    assert reason is not None
    assert reason.observed == 10_000_000
    assert reason.threshold == 50_000_000


def test_required_financial_missing_marks_data_insufficient(quant_frame: pd.DataFrame) -> None:
    """Verify a missing required financial field marks data as insufficient.

    Args:
        quant_frame: Deterministic quant cross-section DataFrame fixture.

    Returns:
        None.
    """
    quant_frame.loc["000001.SZ", "net_profit_ttm"] = None
    result = HardFilterEngine(QuantConfig()).apply(quant_frame)

    filtered = result.by_security["000001.SZ"]
    assert filtered.data_status == DataStatus.INSUFFICIENT
    assert filtered.allowed_for_scoring is False
    assert filtered.reason_by_code("missing_critical_financial") is not None
