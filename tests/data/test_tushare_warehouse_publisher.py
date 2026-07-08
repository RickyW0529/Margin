"""Tushare quality-to-warehouse publication tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from margin.data.sync_models import DataSyncStatus, EndpointSyncResult
from margin.data.tushare_warehouse import TushareWarehousePublisher


class _Stack:
    """In-memory ingestion stack double tracking published records per endpoint."""

    def __init__(self) -> None:
        """Initialize the call log."""
        self.calls: list[tuple[str, str, list[dict[str, Any]]]] = []

    def ingest_security_master(self, work_item: object, **kwargs: Any) -> EndpointSyncResult:
        """Log a security-master ingestion call and return a success result."""
        records = kwargs["raw_records"]
        self.calls.append(("security", "security_master", records))
        return _result(work_item, fact_count=0)

    def ingest_records(self, work_item: object, **kwargs: Any) -> EndpointSyncResult:
        """Log a record ingestion call and return a success result with fact count."""
        records = kwargs["raw_records"]
        self.calls.append(("records", kwargs["endpoint_code"], records))
        return _result(work_item, fact_count=6 * len(records))

    def ingest_indicator_records(
        self,
        work_item: object,
        **kwargs: Any,
    ) -> EndpointSyncResult:
        """Log an indicator ingestion call and return a success result."""
        records = kwargs["raw_records"]
        self.calls.append(("indicators", kwargs["endpoint_code"], records))
        return _result(work_item, fact_count=len(records))


def _result(work_item: object, *, fact_count: int) -> EndpointSyncResult:
    """Build a succeeded ``EndpointSyncResult`` with the given fact count."""
    return EndpointSyncResult(
        work_item_id=getattr(work_item, "work_item_id"),
        status=DataSyncStatus.SUCCEEDED,
        fact_count=fact_count,
    )


def test_daily_publication_normalizes_tushare_units() -> None:
    """Daily source rows enter the unified warehouse contract."""
    stack = _Stack()
    publisher = TushareWarehousePublisher(stack)

    publisher.publish(
        "daily",
        [
            {
                "ts_code": "000001.SZ",
                "trade_date": "20260622",
                "close": 10.5,
                "amount": 200,
            }
        ],
        run_id="run-1",
        decision_at=datetime(2026, 6, 23, tzinfo=UTC),
    )

    record = stack.calls[0][2][0]
    assert stack.calls[0][1] == "daily_bar"
    assert record["symbol"] == "000001.SZ"
    assert record["amount"] == 200_000


def test_financial_publication_maps_quant_indicator_names() -> None:
    """Balance-sheet and audit rows publish fields consumed by hard filters."""
    stack = _Stack()
    publisher = TushareWarehousePublisher(stack)
    decision_at = datetime(2026, 6, 23, tzinfo=UTC)

    publisher.publish(
        "balancesheet",
        [
            {
                "ts_code": "000001.SZ",
                "ann_date": "20260420",
                "end_date": "20251231",
                "total_assets": 100,
                "total_liab": 40,
                "total_hldr_eqy_exc_min_int": 50,
                "goodwill": 5,
                "accounts_receiv": 10,
                "inventories": 20,
            }
        ],
        run_id="run-1",
        decision_at=decision_at,
    )
    publisher.publish(
        "fina_audit",
        [
            {
                "ts_code": "000001.SZ",
                "ann_date": "20260420",
                "end_date": "20251231",
                "audit_result": "标准无保留意见",
            }
        ],
        run_id="run-1",
        decision_at=decision_at,
    )

    balance = stack.calls[0][2][0]
    audit = stack.calls[1][2][0]
    assert balance["liability_ratio"] == 0.4
    assert balance["goodwill_to_equity"] == 0.1
    assert balance["receivable_risk"] == 0.1
    assert balance["inventory_risk"] == 0.2
    assert audit["audit_opinion"] == "标准无保留意见"


def test_ml_lifecycle_extra_publication_maps_indicator_names() -> None:
    """ML lifecycle extra endpoints publish canonical feature fields."""
    stack = _Stack()
    publisher = TushareWarehousePublisher(stack)
    decision_at = datetime(2026, 6, 23, tzinfo=UTC)

    publisher.publish(
        "moneyflow",
        [
            {
                "ts_code": "000001.SZ",
                "trade_date": "20260622",
                "buy_lg_amount": 120,
                "sell_lg_amount": 70,
                "buy_elg_amount": 90,
                "sell_elg_amount": 20,
                "net_mf_amount": 80,
            }
        ],
        run_id="run-1",
        decision_at=decision_at,
    )
    publisher.publish(
        "forecast",
        [
            {
                "ts_code": "000001.SZ",
                "ann_date": "20260420",
                "end_date": "20251231",
                "p_change_min": 20,
                "p_change_max": 40,
            }
        ],
        run_id="run-1",
        decision_at=decision_at,
    )
    publisher.publish(
        "limit_list_d",
        [
            {
                "ts_code": "000001.SZ",
                "trade_date": "20260622",
                "limit": "U",
                "close": 11.0,
                "pct_chg": 10.0,
            }
        ],
        run_id="run-1",
        decision_at=decision_at,
    )

    moneyflow = stack.calls[0][2][0]
    forecast = stack.calls[1][2][0]
    limit = stack.calls[2][2][0]
    assert moneyflow["mf_lg_net_amount"] == 50
    assert moneyflow["mf_elg_net_amount"] == 70
    assert forecast["forecast_p_change_mid"] == 30
    assert limit["limit_flag"] == "U"
    assert limit["limit_trade_blocked"] == 1
