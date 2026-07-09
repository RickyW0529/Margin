"""Tushare source quality-screening tests."""

from __future__ import annotations

from datetime import UTC, datetime

from margin.data.requirements import QuantDataRequirementCatalog
from margin.data.tushare_quality import (
    TushareQualityScreen,
    select_current_non_st_securities,
)
from margin.data.tushare_source import TushareLandingRecord


def _record(api_name: str, payload: dict[str, object]) -> TushareLandingRecord:
    """Build a ``TushareLandingRecord`` fixture from a raw payload.

    Args:
        api_name: str: .
        payload: dict[str, object]: .

    Returns:
        TushareLandingRecord: .
    """
    return TushareLandingRecord.from_payload(
        endpoint=QuantDataRequirementCatalog.default().endpoint("tushare", api_name),
        payload=payload,
        fetched_at=datetime(2026, 6, 23, tzinfo=UTC),
        sync_run_id="run-1",
    )


def test_current_st_rows_are_removed_before_source_persistence() -> None:
    """ST payloads do not enter the non-ST source-system universe.

    Returns:
        None: .
    """
    accepted, excluded = select_current_non_st_securities(
        [
            {"ts_code": "000001.SZ", "name": "平安银行", "list_status": "L"},
            {"ts_code": "000002.SZ", "name": "*ST测试", "list_status": "L"},
            {"ts_code": "600001.SH", "name": "退市测试", "list_status": "D"},
        ]
    )

    assert [row["ts_code"] for row in accepted] == ["000001.SZ"]
    assert excluded == {"st": 1, "not_listed": 1, "invalid_symbol": 0}


def test_future_listings_are_removed_for_as_of_company_pool() -> None:
    """A rolling window ending before list_date must not include future listings.

    Returns:
        None: .
    """
    accepted, excluded = select_current_non_st_securities(
        [
            {
                "ts_code": "000001.SZ",
                "name": "平安银行",
                "list_status": "L",
                "list_date": "19910403",
            },
            {
                "ts_code": "603000.SH",
                "name": "未来股份",
                "list_status": "L",
                "list_date": "20260624",
            },
        ],
        as_of=datetime(2026, 6, 22, tzinfo=UTC),
    )

    assert [row["ts_code"] for row in accepted] == ["000001.SZ"]
    assert excluded == {"st": 0, "not_listed": 1, "invalid_symbol": 0}


def test_delisting_transition_names_are_removed_from_company_pool() -> None:
    """Names prefixed with 退市 are not eligible for the non-ST All-A pool.

    Returns:
        None: .
    """
    accepted, excluded = select_current_non_st_securities(
        [
            {"ts_code": "600636.SH", "name": "退市国化", "list_status": "L"},
        ],
        as_of=datetime(2026, 6, 22, tzinfo=UTC),
    )

    assert accepted == []
    assert excluded == {"st": 0, "not_listed": 1, "invalid_symbol": 0}


def test_quality_accepts_in_window_row_for_eligible_security() -> None:
    """A complete in-window market row can publish to the warehouse.

    Returns:
        None: .
    """
    decision = TushareQualityScreen().evaluate(
        _record(
            "daily",
            {"ts_code": "000001.SZ", "trade_date": "20260622", "close": 10.0},
        ),
        window_start=datetime(2024, 6, 23, tzinfo=UTC),
        window_end=datetime(2026, 6, 23, tzinfo=UTC),
        eligible_symbols={"000001.SZ"},
    )

    assert decision.decision == "accepted"
    assert decision.quality_score == 1
    assert decision.issue_codes == ()


def test_quality_rejects_universe_and_natural_key_violations() -> None:
    """Rows outside the non-ST company pool or without keys cannot publish.

    Returns:
        None: .
    """
    outside = TushareQualityScreen().evaluate(
        _record(
            "daily",
            {"ts_code": "000002.SZ", "trade_date": "20260622", "close": 10.0},
        ),
        window_start=datetime(2024, 6, 23, tzinfo=UTC),
        window_end=datetime(2026, 6, 23, tzinfo=UTC),
        eligible_symbols={"000001.SZ"},
    )
    missing_key = TushareQualityScreen().evaluate(
        _record("daily", {"ts_code": "000001.SZ", "close": 10.0}),
        window_start=datetime(2024, 6, 23, tzinfo=UTC),
        window_end=datetime(2026, 6, 23, tzinfo=UTC),
        eligible_symbols={"000001.SZ"},
    )

    assert outside.decision == "rejected"
    assert "symbol_not_in_company_pool" in outside.issue_codes
    assert missing_key.decision == "rejected"
    assert "missing_natural_key" in missing_key.issue_codes


def test_quality_quarantines_out_of_window_market_rows() -> None:
    """Unexpected old market rows are retained for audit but not published.

    Returns:
        None: .
    """
    decision = TushareQualityScreen().evaluate(
        _record(
            "daily",
            {"ts_code": "000001.SZ", "trade_date": "20230101", "close": 10.0},
        ),
        window_start=datetime(2024, 6, 23, tzinfo=UTC),
        window_end=datetime(2026, 6, 23, tzinfo=UTC),
        eligible_symbols={"000001.SZ"},
    )

    assert decision.decision == "quarantined"
    assert decision.issue_codes == ("outside_rolling_window",)


def test_quality_accepts_trade_calendar_without_security_symbol() -> None:
    """Market-calendar rows use exchange/date keys and are not company scoped.

    Returns:
        None: .
    """
    decision = TushareQualityScreen().evaluate(
        _record(
            "trade_cal",
            {"exchange": "SSE", "cal_date": "20260622", "is_open": 1},
        ),
        window_start=datetime(2024, 6, 23, tzinfo=UTC),
        window_end=datetime(2026, 6, 23, tzinfo=UTC),
        eligible_symbols={"000001.SZ"},
    )

    assert decision.decision == "accepted"


def test_quality_accepts_suspend_rows_with_empty_suspend_timing() -> None:
    """Tushare suspend_d commonly omits suspend_timing; type/date identify the event.

    Returns:
        None: .
    """
    decision = TushareQualityScreen().evaluate(
        _record(
            "suspend_d",
            {
                "ts_code": "600078.SH",
                "trade_date": "20240624",
                "suspend_type": "R",
                "suspend_timing": None,
            },
        ),
        window_start=datetime(2024, 6, 23, tzinfo=UTC),
        window_end=datetime(2026, 6, 23, tzinfo=UTC),
        eligible_symbols={"600078.SH"},
    )

    assert decision.decision == "accepted"
    assert decision.issue_codes == ()
