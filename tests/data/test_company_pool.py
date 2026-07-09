"""Company-pool view materialization tests."""

from __future__ import annotations

from datetime import UTC, datetime

from margin.data.company_pool import (
    build_company_pool_snapshot,
    filter_company_pool_rows_as_of,
)


def test_company_pool_snapshot_is_stable_and_quant_ready() -> None:
    """The serving view becomes an immutable, ordered quant universe.

    Returns:
        None: .
    """
    rows = [
        {
            "security_id": "600000.SH",
            "symbol": "600000.SH",
            "name": "浦发银行",
            "exchange": "SH",
            "industry_code": "bank",
            "industry_name": "银行",
        },
        {
            "security_id": "000001.SZ",
            "symbol": "000001.SZ",
            "name": "平安银行",
            "exchange": "SZ",
            "industry_code": "bank",
            "industry_name": "银行",
        },
    ]
    business_at = datetime(2026, 6, 22, tzinfo=UTC)

    first = build_company_pool_snapshot(
        rows,
        source_run_id="run-1",
        business_at=business_at,
        known_at=business_at,
    )
    replay = build_company_pool_snapshot(
        list(reversed(rows)),
        source_run_id="run-1",
        business_at=business_at,
        known_at=business_at,
    )

    assert first.snapshot_id == replay.snapshot_id
    assert len(first.snapshot_id) <= 64
    assert first.security_ids == ("000001.SZ", "600000.SH")
    assert first.member_count == 2
    assert all(member.included for member in first.members)
    assert all(member.data_status == "pending_quant_input" for member in first.members)


def test_company_pool_rows_filter_future_listings_as_of_business_date() -> None:
    """Materialization excludes rows not listed by the requested business date.

    Returns:
        None: .
    """
    rows = [
        {
            "security_id": "000001.SZ",
            "symbol": "000001.SZ",
            "name": "平安银行",
            "exchange": "SZ",
            "listed_at": "1991-04-03",
        },
        {
            "security_id": "603000.SH",
            "symbol": "603000.SH",
            "name": "未来股份",
            "exchange": "SH",
            "listed_at": "2026-06-24",
        },
        {
            "security_id": "600636.SH",
            "symbol": "600636.SH",
            "name": "退市国化",
            "exchange": "SH",
            "listed_at": "1993-03-16",
        },
    ]

    filtered = filter_company_pool_rows_as_of(
        rows,
        business_at=datetime(2026, 6, 22, tzinfo=UTC),
    )

    assert [row["security_id"] for row in filtered] == ["000001.SZ"]
