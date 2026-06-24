"""Independent Tushare source backfill service tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from margin.data.tushare_backfill import (
    TushareBackfillConfig,
    TushareBackfillService,
)


class _Client:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def query(self, api_name: str, **params: object) -> pd.DataFrame:
        self.calls.append((api_name, params))
        if params.get("offset", 0) not in (0, None):
            return pd.DataFrame()
        if api_name == "stock_basic":
            return pd.DataFrame(
                [
                    {
                        "ts_code": "000001.SZ",
                        "name": "平安银行",
                        "list_status": "L",
                        "industry": "银行",
                    },
                    {
                        "ts_code": "000002.SZ",
                        "name": "*ST测试",
                        "list_status": "L",
                        "industry": "地产",
                    },
                ]
            )
        if api_name == "trade_cal":
            return pd.DataFrame(
                [
                    {"exchange": "SSE", "cal_date": "20260621", "is_open": 1},
                    {"exchange": "SSE", "cal_date": "20260622", "is_open": 1},
                ]
            )
        if api_name == "daily":
            trade_date = str(params["trade_date"])
            return pd.DataFrame(
                [
                    {
                        "ts_code": "000001.SZ",
                        "trade_date": trade_date,
                        "close": 10.0,
                    },
                    {
                        "ts_code": "000002.SZ",
                        "trade_date": trade_date,
                        "close": 20.0,
                    },
                ]
            )
        return pd.DataFrame()


class _FlakyDailyClient(_Client):
    def query(self, api_name: str, **params: object) -> pd.DataFrame:
        if api_name == "daily" and params.get("trade_date") == "20260621":
            raise TimeoutError("slice timeout")
        return super().query(api_name, **params)


class _FlakyIndexWeightClient(_Client):
    def query(self, api_name: str, **params: object) -> pd.DataFrame:
        self.calls.append((api_name, params))
        if params.get("offset", 0) not in (0, None):
            return pd.DataFrame()
        if api_name == "index_weight":
            if params.get("start_date") == "20260201":
                raise TimeoutError("index month timeout")
            return pd.DataFrame(
                [
                    {
                        "index_code": str(params["index_code"]),
                        "con_code": "000001.SZ",
                        "trade_date": str(params["end_date"]),
                        "weight": 1.5,
                    }
                ]
            )
        return super().query(api_name, **params)


class _Repository:
    def __init__(self, *, expected_endpoint_count: int = 3) -> None:
        self.records: list[object] = []
        self.decisions: list[object] = []
        self.finished: tuple[int, dict[str, str]] | None = None
        self.expected_endpoint_count = expected_endpoint_count

    def seed_catalog(self) -> None:
        pass

    def start_run(self, request: object, *, endpoint_count: int) -> str:
        assert endpoint_count == self.expected_endpoint_count
        return "run-1"

    def insert_records(self, records: object) -> int:
        rows = list(records)
        self.records.extend(rows)
        return len(rows)

    def record_quality_decisions(self, decisions: object) -> int:
        rows = list(decisions)
        self.decisions.extend(rows)
        return len(rows)

    def finish_run(
        self,
        run_id: str,
        *,
        completed_count: int,
        failed_endpoints: dict[str, str],
    ) -> None:
        assert run_id == "run-1"
        self.finished = (completed_count, failed_endpoints)


class _Publisher:
    def __init__(self) -> None:
        self.records: dict[str, list[dict[str, object]]] = {}

    def publish(
        self,
        api_name: str,
        records: list[dict[str, object]],
        *,
        run_id: str,
        decision_at: datetime,
    ) -> int:
        assert run_id == "run-1"
        self.records[api_name] = records
        return len(records)


class _Pool:
    def materialize(
        self,
        *,
        source_run_id: str,
        business_at: datetime,
        known_at: datetime,
    ) -> object:
        assert source_run_id == "run-1"
        return type(
            "PoolSnapshot",
            (),
            {"snapshot_id": "pool-1", "member_count": 1},
        )()


def test_backfill_filters_st_and_uses_open_date_slices() -> None:
    """The source run persists only non-ST business rows and bounded date calls."""
    client = _Client()
    repository = _Repository()
    publisher = _Publisher()
    service = TushareBackfillService(
        client=client,
        repository=repository,
        warehouse_publisher=publisher,
        company_pool_repository=_Pool(),
    )

    report = service.run(
        TushareBackfillConfig(
            window_start=datetime(2026, 6, 21, tzinfo=UTC),
            window_end=datetime(2026, 6, 23, tzinfo=UTC),
            endpoints=("daily",),
            idempotency_key="test-run",
        )
    )

    persisted_symbols = {
        row.symbol for row in repository.records if row.symbol is not None
    }
    daily_calls = [
        params for api_name, params in client.calls if api_name == "daily"
    ]
    assert persisted_symbols == {"000001.SZ"}
    assert [call["trade_date"] for call in daily_calls] == [
        "20260622",
        "20260621",
    ]
    assert report.excluded_securities["st"] == 1
    assert report.endpoints["daily"].fetched_rows == 4
    assert report.endpoints["daily"].persisted_rows == 2
    assert report.endpoints["daily"].published_fact_count == 2
    assert {
        row["ts_code"] for row in publisher.records["daily"]
    } == {"000001.SZ"}
    assert report.company_pool_snapshot_id == "pool-1"
    assert report.company_pool_member_count == 1
    assert repository.finished == (3, {})


def test_backfill_retains_date_slice_progress_when_one_slice_fails() -> None:
    """A transient Tushare date-slice failure keeps already persisted slices auditable."""
    client = _FlakyDailyClient()
    repository = _Repository()
    publisher = _Publisher()
    service = TushareBackfillService(
        client=client,
        repository=repository,
        warehouse_publisher=publisher,
    )

    report = service.run(
        TushareBackfillConfig(
            window_start=datetime(2026, 6, 21, tzinfo=UTC),
            window_end=datetime(2026, 6, 23, tzinfo=UTC),
            endpoints=("daily",),
            idempotency_key="flaky-run",
        )
    )

    daily = report.endpoints["daily"]
    assert daily.status == "partial"
    assert daily.fetched_rows == 2
    assert daily.persisted_rows == 1
    assert daily.accepted_rows == 1
    assert daily.published_fact_count == 1
    assert daily.error is not None
    assert "20260621" in daily.error
    assert "slice timeout" in daily.error
    assert publisher.records["daily"][0]["trade_date"] == "20260622"
    assert repository.finished == (2, {"daily": daily.error})


def test_index_weight_backfill_uses_month_slices() -> None:
    """Benchmark constituent weights are sliced monthly instead of one huge range."""
    client = _Client()
    repository = _Repository(expected_endpoint_count=2)
    service = TushareBackfillService(client=client, repository=repository)

    service.run(
        TushareBackfillConfig(
            window_start=datetime(2026, 1, 15, tzinfo=UTC),
            window_end=datetime(2026, 3, 10, tzinfo=UTC),
            endpoints=("index_weight",),
            benchmark_indices=("000300.SH",),
            idempotency_key="index-weight-slices",
        )
    )

    calls = [
        params for api_name, params in client.calls if api_name == "index_weight"
    ]
    assert [
        (call["index_code"], call["start_date"], call["end_date"])
        for call in calls
    ] == [
        ("000300.SH", "20260115", "20260131"),
        ("000300.SH", "20260201", "20260228"),
        ("000300.SH", "20260301", "20260310"),
    ]


def test_index_range_backfill_retains_progress_when_one_slice_fails() -> None:
    """Index-range APIs are streamed by partition so one bad month is auditable."""
    client = _FlakyIndexWeightClient()
    repository = _Repository(expected_endpoint_count=2)
    service = TushareBackfillService(client=client, repository=repository)

    report = service.run(
        TushareBackfillConfig(
            window_start=datetime(2026, 1, 15, tzinfo=UTC),
            window_end=datetime(2026, 3, 10, tzinfo=UTC),
            endpoints=("index_weight",),
            benchmark_indices=("000300.SH",),
            idempotency_key="index-weight-flaky",
        )
    )

    index_weight = report.endpoints["index_weight"]
    rows = [row for row in repository.records if row.endpoint == "index_weight"]
    assert index_weight.status == "partial"
    assert index_weight.fetched_rows == 2
    assert index_weight.persisted_rows == 2
    assert index_weight.accepted_rows == 2
    assert index_weight.request_count == 3
    assert index_weight.error is not None
    assert "20260201" in index_weight.error
    assert "index month timeout" in index_weight.error
    assert [row.business_date.isoformat() for row in rows] == [
        "2026-01-31",
        "2026-03-10",
    ]
    assert repository.finished == (1, {"index_weight": index_weight.error})
