"""Tushare independent source-system contract tests."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from margin.data.requirements import QuantDataRequirementCatalog
from margin.data.tushare_repository import (
    chunk_landing_records,
    chunk_quality_decisions,
    landing_insert_values,
    landing_table_columns,
)
from margin.data.tushare_source import (
    TushareLandingRecord,
    TushareSourceCatalog,
    is_st_security_name,
)


def test_source_catalog_has_one_table_per_admitted_api() -> None:
    """Every admitted API owns an independent landing table.

    Returns:
        None: .
    """
    catalog = TushareSourceCatalog(QuantDataRequirementCatalog.default())

    table_names = set(catalog.table_names())

    assert "source_tushare.ts_daily" in table_names
    assert "source_tushare.ts_income" in table_names
    assert "source_tushare.ts_pledge_stat" in table_names
    assert "source_tushare.ts_stock_basic" in table_names
    assert "source_tushare.ts_top_list" not in table_names
    assert len(table_names) == len(
        QuantDataRequirementCatalog.default().enabled_endpoints("tushare")
    )


def test_landing_table_contract_supports_pit_quality_and_index_access() -> None:
    """Dedicated tables expose the shared lineage and query-access columns.

    Returns:
        None: .
    """
    columns = set(landing_table_columns("daily"))

    assert {
        "natural_key_hash",
        "revision_hash",
        "symbol",
        "business_date",
        "published_at",
        "available_at",
        "raw_payload",
        "sync_run_id",
        "quality_status",
    } <= columns


def test_landing_insert_values_contain_only_physical_columns() -> None:
    """Logical endpoint routing metadata must not leak into SQL INSERT columns.

    Returns:
        None: .
    """
    record = TushareLandingRecord.from_payload(
        endpoint=QuantDataRequirementCatalog.default().endpoint("tushare", "daily"),
        payload={
            "ts_code": "000001.SZ",
            "trade_date": "20260622",
            "close": 10.0,
        },
        fetched_at=datetime(2026, 6, 23, 8, tzinfo=UTC),
        sync_run_id="run-1",
    )

    values = landing_insert_values(record)

    assert "endpoint" not in values
    assert set(values) <= set(landing_table_columns("daily"))


def test_landing_batches_stay_below_postgres_parameter_limit() -> None:
    """Large All-A pages are split before SQL parameter compilation.

    Returns:
        None: .
    """
    records = list(range(5312))

    batches = list(chunk_landing_records(records, batch_size=1000))

    assert [len(batch) for batch in batches] == [1000, 1000, 1000, 1000, 1000, 312]


def test_quality_decision_batches_stay_below_postgres_parameter_limit() -> None:
    """Large benchmark-weight pages split quality INSERT statements too.

    Returns:
        None: .
    """
    decisions = list(range(6000))

    batches = list(chunk_quality_decisions(decisions, batch_size=1000))

    assert [len(batch) for batch in batches] == [1000, 1000, 1000, 1000, 1000, 1000]


def test_landing_record_is_idempotent_by_natural_key_and_revision() -> None:
    """Same business row/revision is stable while corrected payload is append-only.

    Returns:
        None: .
    """
    fetched_at = datetime(2026, 6, 23, 8, tzinfo=UTC)
    first = TushareLandingRecord.from_payload(
        endpoint=QuantDataRequirementCatalog.default().endpoint("tushare", "daily"),
        payload={
            "ts_code": "000001.SZ",
            "trade_date": "20260622",
            "close": 10.0,
        },
        fetched_at=fetched_at,
        sync_run_id="run-1",
    )
    replay = TushareLandingRecord.from_payload(
        endpoint=QuantDataRequirementCatalog.default().endpoint("tushare", "daily"),
        payload={
            "ts_code": "000001.SZ",
            "trade_date": "20260622",
            "close": 10.0,
        },
        fetched_at=fetched_at,
        sync_run_id="run-2",
    )
    correction = TushareLandingRecord.from_payload(
        endpoint=QuantDataRequirementCatalog.default().endpoint("tushare", "daily"),
        payload={
            "ts_code": "000001.SZ",
            "trade_date": "20260622",
            "close": 10.1,
        },
        fetched_at=fetched_at,
        sync_run_id="run-3",
    )

    assert first.natural_key_hash == replay.natural_key_hash
    assert first.revision_hash == replay.revision_hash
    assert first.source_row_id == replay.source_row_id
    assert correction.natural_key_hash == first.natural_key_hash
    assert correction.revision_hash != first.revision_hash
    assert correction.source_row_id != first.source_row_id
    assert first.symbol == "000001.SZ"
    assert first.business_date == date(2026, 6, 22)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("*ST测试", True),
        ("ST测试", True),
        ("S*ST测试", True),
        ("平安银行", False),
        ("恒生电子", False),
    ],
)
def test_st_name_detection(name: str, expected: bool) -> None:
    """Current ST variants are excluded before business-detail persistence.

    Args:
        name: str: .
        expected: bool: .

    Returns:
        None: .
    """
    assert is_st_security_name(name) is expected
