"""Rolling quant-only backfill into the independent Tushare source system."""

from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol

from pydantic import BaseModel, Field, field_validator

from margin.data.requirements import QuantDataRequirementCatalog
from margin.data.sync_models import DataSyncRequest
from margin.data.tushare_quality import (
    SourceQualityDecision,
    TushareQualityScreen,
    select_current_non_st_securities,
)
from margin.data.tushare_query import TushareQueryCatalog
from margin.data.tushare_source import TushareLandingRecord
from margin.news.models import ensure_utc

_COMPANY_SYMBOL_ENDPOINTS = {
    "namechange",
    "daily",
    "adj_factor",
    "suspend_d",
    "daily_basic",
    "income",
    "balancesheet",
    "cashflow",
    "fina_indicator",
    "fina_audit",
    "index_member",
    "pledge_stat",
    "index_weight",
}


class TushareClient(Protocol):
    """Minimal dynamic Tushare Pro client contract."""

    def query(self, api_name: str, **params: Any) -> Any:
        """Return a pandas-compatible frame."""


class TushareSourceRepository(Protocol):
    """Persistence boundary used by the rolling backfill."""

    def seed_catalog(self) -> None:
        """Persist the versioned endpoint closure."""

    def start_run(self, request: DataSyncRequest, *, endpoint_count: int) -> str:
        """Start an audited source run."""

    def insert_records(self, records: Iterable[TushareLandingRecord]) -> int:
        """Insert one endpoint batch."""

    def record_quality_decisions(
        self,
        decisions: Iterable[SourceQualityDecision],
    ) -> int:
        """Persist quality decisions."""

    def finish_run(
        self,
        run_id: str,
        *,
        completed_count: int,
        failed_endpoints: dict[str, str],
    ) -> None:
        """Finish the audited source run."""


class TushareWarehousePublication(Protocol):
    """Quality-to-warehouse publication boundary."""

    def publish(
        self,
        api_name: str,
        records: list[dict[str, Any]],
        *,
        run_id: str,
        decision_at: datetime,
    ) -> int:
        """Publish accepted rows and return inserted fact count."""


class CompanyPoolMaterialization(Protocol):
    """Warehouse-to-company-pool snapshot boundary."""

    def materialize(
        self,
        *,
        source_run_id: str,
        business_at: datetime,
        known_at: datetime,
    ) -> Any:
        """Freeze the current non-ST serving view."""


class TushareBackfillConfig(BaseModel):
    """Frozen rolling-window source extraction policy."""

    window_start: datetime
    window_end: datetime
    financial_comparison_years: int = Field(default=1, ge=1, le=3)
    endpoints: tuple[str, ...] = ()
    benchmark_indices: tuple[str, ...] = (
        "000300.SH",
        "000905.SH",
        "000852.SH",
    )
    page_size: int = Field(default=5000, ge=100, le=6000)
    symbol_batch_size: int = Field(default=200, ge=1, le=500)
    idempotency_key: str

    model_config = {"frozen": True}

    @field_validator("window_start", "window_end")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        """Normalize policy bounds to UTC."""
        return ensure_utc(value)


class TushareEndpointCoverage(BaseModel):
    """Per-endpoint extraction and quality counts."""

    api_name: str
    fetched_rows: int = 0
    persisted_rows: int = 0
    accepted_rows: int = 0
    quarantined_rows: int = 0
    rejected_rows: int = 0
    published_fact_count: int = 0
    request_count: int = 0
    status: str = "succeeded"
    error: str | None = None


class TushareBackfillReport(BaseModel):
    """Auditable coverage report for one rolling source run."""

    run_id: str
    eligible_security_count: int
    excluded_securities: dict[str, int]
    endpoints: dict[str, TushareEndpointCoverage]
    company_pool_snapshot_id: str | None = None
    company_pool_member_count: int = 0
    started_at: datetime
    finished_at: datetime


class TushareBackfillService:
    """Execute bounded All-A extraction, source persistence, and quality screening."""

    def __init__(
        self,
        *,
        client: TushareClient,
        repository: TushareSourceRepository,
        quality_screen: TushareQualityScreen | None = None,
        requirements: QuantDataRequirementCatalog | None = None,
        queries: TushareQueryCatalog | None = None,
        warehouse_publisher: TushareWarehousePublication | None = None,
        company_pool_repository: CompanyPoolMaterialization | None = None,
    ) -> None:
        """Initialize source extraction dependencies."""
        self._client = client
        self._repository = repository
        self._quality = quality_screen or TushareQualityScreen()
        self._requirements = requirements or QuantDataRequirementCatalog.default()
        self._queries = queries or TushareQueryCatalog.default()
        self._warehouse_publisher = warehouse_publisher
        self._company_pool_repository = company_pool_repository

    def run(self, config: TushareBackfillConfig) -> TushareBackfillReport:
        """Run the selected endpoint closure and continue safely after endpoint failures."""
        started_at = datetime.now(UTC)
        endpoints = config.endpoints or self._queries.api_names()
        unknown = set(endpoints).difference(self._queries.api_names())
        if unknown:
            raise ValueError(f"unknown Tushare endpoint: {sorted(unknown)[0]}")
        if "stock_basic" not in endpoints:
            endpoints = ("stock_basic", *endpoints)
        if any(self._queries.get(name).query_mode == "date_slice" for name in endpoints):
            if "trade_cal" not in endpoints:
                endpoints = (*endpoints, "trade_cal")
        endpoints = _ordered_endpoints(tuple(dict.fromkeys(endpoints)))

        self._repository.seed_catalog()
        request = DataSyncRequest(
            provider="tushare",
            endpoint_codes=endpoints,
            requested_by="tushare_source_backfill",
            backfill_start=config.window_start,
            backfill_end=config.window_end,
            window_start=config.window_start,
            window_end=config.window_end,
            idempotency_key=config.idempotency_key,
        )
        run_id = self._repository.start_run(request, endpoint_count=len(endpoints))
        coverage: dict[str, TushareEndpointCoverage] = {}
        failures: dict[str, str] = {}

        stock_rows, stock_requests = self._fetch(
            "stock_basic",
            [{"exchange": "", "list_status": "L"}],
            page_size=config.page_size,
        )
        eligible_rows, excluded = select_current_non_st_securities(
            stock_rows,
            as_of=config.window_end,
        )
        eligible_symbols = {
            str(row["ts_code"]).strip().upper() for row in eligible_rows
        }
        coverage["stock_basic"] = self._persist(
            "stock_basic",
            eligible_rows,
            fetched_count=len(stock_rows),
            request_count=stock_requests,
            run_id=run_id,
            config=config,
            eligible_symbols=eligible_symbols,
        )

        open_dates: list[date] = []
        industry_codes: tuple[str, ...] = ()
        for api_name in endpoints:
            if api_name == "stock_basic":
                continue
            try:
                requests = self._requests(
                    api_name,
                    config=config,
                    open_dates=open_dates,
                    industry_codes=industry_codes,
                    eligible_symbols=eligible_symbols,
                )
                query_mode = self._queries.get(api_name).query_mode
                if query_mode in {
                    "date_slice",
                    "period_slice",
                    "symbol_batch",
                    "index_range",
                }:
                    endpoint_coverage = TushareEndpointCoverage(api_name=api_name)
                    request_failures: list[str] = []
                    for request_params in requests:
                        try:
                            rows, request_count = self._fetch(
                                api_name,
                                [request_params],
                                page_size=config.page_size,
                            )
                        except Exception as exc:  # noqa: BLE001 - isolate one slice.
                            endpoint_coverage.request_count += 1
                            request_failures.append(
                                _request_failure_message(
                                    api_name,
                                    request_params,
                                    exc,
                                )
                            )
                            continue
                        filtered_rows = _filter_company_rows(
                            api_name,
                            rows,
                            eligible_symbols,
                        )
                        part = self._persist(
                            api_name,
                            filtered_rows,
                            fetched_count=len(rows),
                            request_count=request_count,
                            run_id=run_id,
                            config=config,
                            eligible_symbols=eligible_symbols,
                        )
                        endpoint_coverage = _merge_coverage(
                            endpoint_coverage,
                            part,
                        )
                    if request_failures:
                        endpoint_coverage.status = (
                            "partial"
                            if endpoint_coverage.fetched_rows
                            else "failed"
                        )
                        endpoint_coverage.error = _summarize_request_failures(
                            request_failures,
                        )
                        failures[api_name] = endpoint_coverage.error
                    coverage[api_name] = endpoint_coverage
                    continue
                rows, request_count = self._fetch(
                    api_name,
                    requests,
                    page_size=config.page_size,
                )
                if api_name == "trade_cal":
                    open_dates = sorted(
                        {
                            parsed
                            for row in rows
                            if int(row.get("is_open") or 0) == 1
                            if (parsed := _parse_date(row.get("cal_date"))) is not None
                        }
                    )
                if api_name == "index_classify":
                    industry_codes = tuple(
                        str(row.get("index_code") or "").strip()
                        for row in rows
                        if str(row.get("index_code") or "").strip()
                    )
                filtered_rows = _filter_company_rows(
                    api_name,
                    rows,
                    eligible_symbols,
                )
                coverage[api_name] = self._persist(
                    api_name,
                    filtered_rows,
                    fetched_count=len(rows),
                    request_count=request_count,
                    run_id=run_id,
                    config=config,
                    eligible_symbols=eligible_symbols,
                )
            except Exception as exc:  # noqa: BLE001 - endpoint isolation is intentional.
                message = str(exc)[:500]
                failures[api_name] = message
                coverage[api_name] = TushareEndpointCoverage(
                    api_name=api_name,
                    status="failed",
                    error=message,
                )

        company_pool_snapshot_id: str | None = None
        company_pool_member_count = 0
        if self._company_pool_repository is not None and "stock_basic" not in failures:
            try:
                pool = self._company_pool_repository.materialize(
                    source_run_id=run_id,
                    business_at=config.window_end,
                    known_at=datetime.now(UTC),
                )
                company_pool_snapshot_id = str(pool.snapshot_id)
                company_pool_member_count = int(pool.member_count)
            except Exception as exc:  # noqa: BLE001 - run records pool degradation.
                failures["company_pool"] = str(exc)[:500]
        completed_count = sum(item.status == "succeeded" for item in coverage.values())
        self._repository.finish_run(
            run_id,
            completed_count=completed_count,
            failed_endpoints=failures,
        )
        return TushareBackfillReport(
            run_id=run_id,
            eligible_security_count=len(eligible_symbols),
            excluded_securities=excluded,
            endpoints=coverage,
            company_pool_snapshot_id=company_pool_snapshot_id,
            company_pool_member_count=company_pool_member_count,
            started_at=started_at,
            finished_at=datetime.now(UTC),
        )

    def _fetch(
        self,
        api_name: str,
        requests: Iterable[dict[str, Any]],
        *,
        page_size: int,
    ) -> tuple[list[dict[str, Any]], int]:
        """Fetch and sanitize all pages for a bounded list of API requests."""
        fields = self._queries.get(api_name).fields_csv
        records: list[dict[str, Any]] = []
        request_count = 0
        for base_params in requests:
            offset = 0
            while True:
                frame = self._client.query(
                    api_name,
                    **base_params,
                    fields=fields,
                    limit=page_size,
                    offset=offset,
                )
                request_count += 1
                page = [
                    {key: _sanitize(value) for key, value in row.items()}
                    for row in frame.to_dict(orient="records")
                ]
                records.extend(page)
                if len(page) < page_size:
                    break
                offset += page_size
        return records, request_count

    def _persist(
        self,
        api_name: str,
        rows: list[dict[str, Any]],
        *,
        fetched_count: int,
        request_count: int,
        run_id: str,
        config: TushareBackfillConfig,
        eligible_symbols: set[str],
    ) -> TushareEndpointCoverage:
        endpoint = self._requirements.endpoint("tushare", api_name)
        fetched_at = datetime.now(UTC)
        landing = [
            TushareLandingRecord.from_payload(
                endpoint=endpoint,
                payload=row,
                fetched_at=fetched_at,
                sync_run_id=run_id,
            )
            for row in rows
        ]
        inserted = self._repository.insert_records(landing)
        decisions = [
            self._quality.evaluate(
                record,
                window_start=config.window_start,
                window_end=config.window_end,
                eligible_symbols=eligible_symbols,
            )
            for record in landing
        ]
        self._repository.record_quality_decisions(decisions)
        accepted_records = [
            row
            for row, decision in zip(rows, decisions, strict=True)
            if decision.decision == "accepted"
        ]
        published_fact_count = (
            self._warehouse_publisher.publish(
                api_name,
                accepted_records,
                run_id=run_id,
                decision_at=config.window_end,
            )
            if self._warehouse_publisher is not None
            else 0
        )
        return TushareEndpointCoverage(
            api_name=api_name,
            fetched_rows=fetched_count,
            persisted_rows=inserted,
            accepted_rows=sum(item.decision == "accepted" for item in decisions),
            quarantined_rows=sum(item.decision == "quarantined" for item in decisions),
            rejected_rows=sum(item.decision == "rejected" for item in decisions),
            published_fact_count=published_fact_count,
            request_count=request_count,
        )

    def _requests(
        self,
        api_name: str,
        *,
        config: TushareBackfillConfig,
        open_dates: list[date],
        industry_codes: tuple[str, ...],
        eligible_symbols: set[str],
    ) -> list[dict[str, Any]]:
        mode = self._queries.get(api_name).query_mode
        start = config.window_start.strftime("%Y%m%d")
        end = config.window_end.strftime("%Y%m%d")
        if api_name == "trade_cal":
            return [{"exchange": "SSE", "start_date": start, "end_date": end}]
        if mode == "date_slice":
            dates = open_dates or _calendar_dates(
                config.window_start.date(),
                config.window_end.date(),
            )
            return [
                {"trade_date": value.strftime("%Y%m%d")}
                for value in sorted(dates, reverse=True)
            ]
        if mode == "period_slice":
            comparison_start = config.window_start.date().replace(
                year=config.window_start.year - config.financial_comparison_years
            )
            return [
                {"period" if api_name != "pledge_stat" else "end_date": value}
                for value in _quarter_ends(comparison_start, config.window_end.date())
            ]
        if mode == "symbol_batch":
            comparison_start = config.window_start.date().replace(
                year=config.window_start.year - config.financial_comparison_years
            )
            symbols = sorted(eligible_symbols)
            return [
                {
                    "ts_code": ",".join(
                        symbols[offset : offset + config.symbol_batch_size]
                    ),
                    "start_date": comparison_start.strftime("%Y%m%d"),
                    "end_date": end,
                }
                for offset in range(
                    0,
                    len(symbols),
                    config.symbol_batch_size,
                )
            ]
        if api_name == "namechange":
            return [{}]
        if api_name == "index_classify":
            return [{"level": "L1", "src": "SW2021"}]
        if api_name == "index_member":
            return [{"index_code": code} for code in industry_codes]
        if api_name == "index_daily":
            return [
                {"ts_code": code, "start_date": start, "end_date": end}
                for code in config.benchmark_indices
            ]
        if api_name == "index_weight":
            return [
                {
                    "index_code": code,
                    "start_date": range_start,
                    "end_date": range_end,
                }
                for code in config.benchmark_indices
                for range_start, range_end in _month_ranges(
                    config.window_start.date(),
                    config.window_end.date(),
                )
            ]
        return [{}]


def _filter_company_rows(
    api_name: str,
    rows: list[dict[str, Any]],
    eligible_symbols: set[str],
) -> list[dict[str, Any]]:
    if api_name not in _COMPANY_SYMBOL_ENDPOINTS:
        return rows
    symbol_field = "con_code" if api_name in {"index_member", "index_weight"} else "ts_code"
    return [
        row
        for row in rows
        if str(row.get(symbol_field) or "").strip().upper() in eligible_symbols
    ]


def _sanitize(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def _parse_date(value: Any) -> date | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    try:
        return datetime.strptime(normalized[:8], "%Y%m%d").date()
    except ValueError:
        return None


def _calendar_dates(start: date, end: date) -> list[date]:
    values: list[date] = []
    current = start
    while current <= end:
        values.append(current)
        current += timedelta(days=1)
    return values


def _quarter_ends(start: date, end: date) -> list[str]:
    values: list[str] = []
    for year in range(start.year, end.year + 1):
        for month, day in ((3, 31), (6, 30), (9, 30), (12, 31)):
            value = date(year, month, day)
            if start <= value <= end:
                values.append(value.strftime("%Y%m%d"))
    return sorted(values, reverse=True)


def _month_ranges(start: date, end: date) -> list[tuple[str, str]]:
    """Return bounded month slices in provider date format."""
    ranges: list[tuple[str, str]] = []
    current = date(start.year, start.month, 1)
    while current <= end:
        next_month = (
            date(current.year + 1, 1, 1)
            if current.month == 12
            else date(current.year, current.month + 1, 1)
        )
        range_start = max(start, current)
        range_end = min(end, next_month - timedelta(days=1))
        ranges.append(
            (
                range_start.strftime("%Y%m%d"),
                range_end.strftime("%Y%m%d"),
            )
        )
        current = next_month
    return ranges


def _ordered_endpoints(endpoints: tuple[str, ...]) -> tuple[str, ...]:
    """Order endpoint dependencies before independent consumers."""
    priority = {
        "stock_basic": 0,
        "trade_cal": 1,
        "index_classify": 2,
        "index_member": 3,
    }
    return tuple(
        sorted(
            endpoints,
            key=lambda name: (priority.get(name, 10), name),
        )
    )


def _merge_coverage(
    current: TushareEndpointCoverage,
    addition: TushareEndpointCoverage,
) -> TushareEndpointCoverage:
    """Aggregate streamed request coverage without retaining source rows."""
    return TushareEndpointCoverage(
        api_name=current.api_name,
        fetched_rows=current.fetched_rows + addition.fetched_rows,
        persisted_rows=current.persisted_rows + addition.persisted_rows,
        accepted_rows=current.accepted_rows + addition.accepted_rows,
        quarantined_rows=current.quarantined_rows + addition.quarantined_rows,
        rejected_rows=current.rejected_rows + addition.rejected_rows,
        published_fact_count=(
            current.published_fact_count + addition.published_fact_count
        ),
        request_count=current.request_count + addition.request_count,
        status="succeeded",
    )


def _request_failure_message(
    api_name: str,
    request_params: dict[str, Any],
    exc: Exception,
) -> str:
    """Return a compact, secret-free partition failure message."""
    key_fields = (
        "trade_date",
        "period",
        "end_date",
        "ts_code",
        "index_code",
        "start_date",
        "end_date",
    )
    partition = {
        key: request_params[key]
        for key in key_fields
        if key in request_params
    }
    return f"{api_name} {partition}: {str(exc)[:240]}"


def _summarize_request_failures(messages: list[str]) -> str:
    """Bound endpoint error text while preserving representative failed slices."""
    if len(messages) <= 3:
        return "; ".join(messages)
    return "; ".join(messages[:3]) + f"; ... {len(messages) - 3} more slice failures"
