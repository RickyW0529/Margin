"""Publish accepted Tushare source rows into the unified PIT warehouse."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from margin.data.providers.tushare_provider import (
    _derive_income_metrics,
    _map_adjustment_row,
    _map_financial_row,
    _map_valuation_row,
)
from margin.data.sync_models import DataSyncStatus, EndpointWorkItem
from margin.data.tushare_source import is_st_security_name
from margin.news.models import ensure_utc


class TushareWarehousePublisher:
    """Translate quality-accepted source rows into existing warehouse contracts."""

    def __init__(self, stack: Any) -> None:
        """Initialize with the production warehouse ingestion stack.

        Args:
            stack: The ``DataWarehouseIngestionStack`` used to persist rows.
        """
        self._stack = stack

    def publish(
        self,
        api_name: str,
        records: list[dict[str, Any]],
        *,
        run_id: str,
        decision_at: datetime,
    ) -> int:
        """Publish one accepted endpoint batch and return inserted fact count.

        Args:
            api_name: The Tushare API name being published.
            records: Quality-accepted source rows to publish.
            run_id: The source-system sync run ID.
            decision_at: The point-in-time decision timestamp.

        Returns:
            The number of facts inserted into the warehouse.
        """
        if not records:
            return 0
        observed_at = ensure_utc(decision_at)
        item = EndpointWorkItem(
            work_item_id=f"publish_{run_id}_{api_name}"[:64],
            run_id=run_id,
            provider="tushare",
            endpoint_code=api_name,
            status=DataSyncStatus.RUNNING,
        )
        if api_name == "stock_basic":
            result = self._stack.ingest_security_master(
                item,
                provider="tushare",
                raw_records=[
                    {
                        "symbol": row.get("ts_code"),
                        "name": row.get("name"),
                        "industry": row.get("industry"),
                        "market": row.get("market"),
                        "list_date": row.get("list_date"),
                    }
                    for row in records
                ],
                decision_at=observed_at,
            )
            return result.fact_count
        if api_name == "daily":
            mapped = [
                {
                    "symbol": row.get("ts_code"),
                    "date": row.get("trade_date"),
                    "close": _number(row.get("close")),
                    "amount": _scaled_number(row.get("amount"), 1000.0),
                    "fetched_at": observed_at,
                    "available_at": row.get("trade_date"),
                    "source": "tushare",
                }
                for row in records
            ]
            result = self._stack.ingest_indicator_records(
                item,
                provider="tushare",
                endpoint_code="daily_bar",
                raw_records=mapped,
                decision_at=observed_at,
            )
            return result.fact_count
        mapped = self._indicator_records(api_name, records, observed_at)
        if not mapped:
            return 0
        result = self._stack.ingest_indicator_records(
            item,
            provider="tushare",
            endpoint_code=api_name,
            raw_records=mapped,
            decision_at=observed_at,
        )
        return result.fact_count

    def _indicator_records(
        self,
        api_name: str,
        records: list[dict[str, Any]],
        fetched_at: datetime,
    ) -> list[dict[str, Any]]:
        """Map accepted source rows to warehouse indicator records by API."""
        if api_name == "adj_factor":
            return [
                _map_adjustment_row(
                    row,
                    ts_code=str(row["ts_code"]),
                    fetched_at=fetched_at,
                )
                for row in records
            ]
        if api_name == "daily_basic":
            return [
                _map_valuation_row(
                    row,
                    ts_code=str(row["ts_code"]),
                    fetched_at=fetched_at,
                )
                for row in records
            ]
        if api_name == "fina_indicator":
            return [
                {
                    **_map_financial_row(
                        row,
                        ts_code=str(row["ts_code"]),
                        fetched_at=fetched_at,
                    ),
                    "roic_ttm": _percent_ratio(row.get("roic")),
                    "interest_coverage": _number(row.get("ebit_to_interest")),
                }
                for row in records
            ]
        if api_name == "income":
            derived = _derive_income_metrics(records)
            return [
                {
                    **_financial_base(row, fetched_at),
                    "revenue": _number(row.get("revenue") or row.get("total_revenue")),
                    "operating_profit": _number(row.get("operate_profit")),
                    "total_profit": _number(row.get("total_profit")),
                    "net_profit": _number(row.get("n_income_attr_p")),
                    "ebit": _number(row.get("ebit")),
                    "ebitda": _number(row.get("ebitda")),
                    **derived.get(
                        (str(row.get("ts_code") or ""), str(row.get("end_date") or "")),
                        {},
                    ),
                }
                for row in records
            ]
        if api_name == "balancesheet":
            return [_balance_record(row, fetched_at) for row in records]
        if api_name == "cashflow":
            return [
                {
                    **_financial_base(row, fetched_at),
                    "operating_cashflow": _number(row.get("n_cashflow_act")),
                    "investing_cashflow": _number(row.get("n_cashflow_inv_act")),
                    "financing_cashflow": _number(row.get("n_cash_flows_fnc_act")),
                    "capital_expenditure": _number(row.get("c_pay_acq_const_fiolta")),
                    "free_cashflow": _number(row.get("free_cashflow")),
                }
                for row in records
            ]
        if api_name == "fina_audit":
            return [
                {
                    **_financial_base(row, fetched_at),
                    "audit_opinion": str(row.get("audit_result") or "").strip(),
                }
                for row in records
            ]
        if api_name == "pledge_stat":
            return [
                {
                    **_financial_base(row, fetched_at),
                    "pledge_ratio": _percent_ratio(row.get("pledge_ratio")),
                }
                for row in records
            ]
        if api_name == "suspend_d":
            return [
                {
                    "symbol": row.get("ts_code"),
                    "trade_date": row.get("trade_date"),
                    "is_suspended": 1,
                    "suspend_type": str(row.get("suspend_type") or ""),
                    "fetched_at": fetched_at,
                    "available_at": row.get("trade_date"),
                    "source": "tushare",
                }
                for row in records
            ]
        if api_name == "namechange":
            return [
                {
                    "symbol": row.get("ts_code"),
                    "report_date": row.get("start_date"),
                    "ann_date": row.get("ann_date") or row.get("start_date"),
                    "is_st": int(is_st_security_name(str(row.get("name") or ""))),
                    "security_name": str(row.get("name") or ""),
                    "fetched_at": fetched_at,
                    "available_at": row.get("ann_date") or row.get("start_date"),
                    "source": "tushare",
                }
                for row in records
            ]
        if api_name == "index_daily":
            return [
                {
                    "symbol": row.get("ts_code"),
                    "trade_date": row.get("trade_date"),
                    "index_close": _number(row.get("close")),
                    "index_return": _percent_ratio(row.get("pct_chg")),
                    "fetched_at": fetched_at,
                    "available_at": row.get("trade_date"),
                    "source": "tushare",
                }
                for row in records
            ]
        if api_name == "index_weight":
            return [
                {
                    "symbol": row.get("con_code"),
                    "trade_date": row.get("trade_date"),
                    "index_weight": _percent_ratio(row.get("weight")),
                    "index_code": row.get("index_code"),
                    "fetched_at": fetched_at,
                    "available_at": row.get("trade_date"),
                    "source": "tushare",
                }
                for row in records
            ]
        return []


def _financial_base(row: dict[str, Any], fetched_at: datetime) -> dict[str, Any]:
    """Return shared financial record fields from one source row."""
    announced = row.get("f_ann_date") or row.get("ann_date") or row.get("end_date")
    return {
        "symbol": row.get("ts_code"),
        "report_date": row.get("end_date"),
        "ann_date": announced,
        "fetched_at": fetched_at,
        "available_at": announced,
        "source": "tushare",
    }


def _balance_record(row: dict[str, Any], fetched_at: datetime) -> dict[str, Any]:
    """Map one balance-sheet row to warehouse indicator fields."""
    assets = _number(row.get("total_assets"))
    liabilities = _number(row.get("total_liab"))
    equity = _number(row.get("total_hldr_eqy_exc_min_int"))
    return {
        **_financial_base(row, fetched_at),
        "total_assets": assets,
        "total_liabilities": liabilities,
        "total_equity": equity,
        "liability_ratio": _divide(liabilities, assets),
        "goodwill_to_equity": _divide(_number(row.get("goodwill")), equity),
        "receivable_risk": _divide(_number(row.get("accounts_receiv")), assets),
        "inventory_risk": _divide(_number(row.get("inventories")), assets),
    }


def _divide(numerator: float | None, denominator: float | None) -> float | None:
    """Return a safe ratio, or ``None`` when the denominator is missing or zero."""
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def _number(value: Any) -> float | None:
    """Convert a provider value to a float, or ``None`` when blank."""
    if value is None or value == "":
        return None
    return float(value)


def _percent_ratio(value: Any) -> float | None:
    """Normalize a percentage field to a decimal ratio."""
    number = _number(value)
    return number / 100.0 if number is not None else None


def _scaled_number(value: Any, multiplier: float) -> float | None:
    """Return a numeric value scaled by a multiplier, or ``None``."""
    number = _number(value)
    return number * multiplier if number is not None else None
