"""AKShare 数据 Provider — A 股行情、基础财务、指数、部分公告元数据。

对应 spec 01 §3 接口契约、架构 §4.2.1。
对应 plan 0102.1 / 0102.3 / 0102.4。
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Any

from margin.core.provider import (
    BaseProvider,
    HealthCheckResult,
    ProviderDescriptor,
    ProviderStatus,
    ProviderType,
)


def _sz_sh_symbol(raw: str) -> str:
    """将 AKShare 原始代码转为标准 ``000001.SZ`` / ``600000.SH`` 口径。"""
    raw = str(raw).strip()
    if raw.startswith(("SH", "SZ")):
        return f"{raw[2:]}.{raw[:2]}"
    if len(raw) == 6:
        if raw.startswith(("60", "68", "9")):
            return f"{raw}.SH"
        return f"{raw}.SZ"
    return raw


def _fmt_date(d: datetime) -> str:
    return d.strftime("%Y%m%d")


def _market_bar_available_at(trade_date: datetime) -> datetime:
    return datetime.combine(trade_date.date(), time(hour=15))


def _parse_optional_date(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    value_str = str(value)
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(value_str[:10], fmt)
        except ValueError:
            continue
    return None


class AKShareProvider(BaseProvider):
    """基于 AKShare 的 A 股市场数据 Provider。

    AKShare 免 token，但需遵守其频率限制。
    所有方法返回标准格式 dict 列表，含时点字段。
    """

    def __init__(self) -> None:
        self._descriptor = ProviderDescriptor(
            name="akshare",
            version="1.0.0",
            provider_type=ProviderType.MARKET_DATA,
            capabilities=[
                "get_securities",
                "get_bars",
                "get_adjustment_factors",
                "get_financials",
                "get_index_members",
            ],
            secret_refs=[],
            config={"license": "free", "limits": "尊重 akshare 频率限制"},
        )

    @property
    def descriptor(self) -> ProviderDescriptor:
        return self._descriptor

    def healthcheck(self) -> HealthCheckResult:
        import akshare as ak

        try:
            ak.stock_zh_a_spot_em()
            return HealthCheckResult(
                provider_name="akshare",
                status=ProviderStatus.HEALTHY,
                checked_at=datetime.now(),
                message="stock_zh_a_spot_em ok",
            )
        except Exception as exc:
            return HealthCheckResult(
                provider_name="akshare",
                status=ProviderStatus.UNHEALTHY,
                checked_at=datetime.now(),
                message=str(exc),
            )

    def get_securities(self, as_of: datetime) -> list[dict[str, Any]]:
        import akshare as ak

        df = ak.stock_zh_a_spot_em()
        fetched_at = datetime.now()
        result: list[dict[str, Any]] = []
        for _, row in df.iterrows():
            result.append(
                {
                    "symbol": _sz_sh_symbol(row["代码"]),
                    "name": row["名称"],
                    "close": float(row.get("最新价", 0) or 0),
                    "fetched_at": fetched_at,
                    "available_at": fetched_at,
                    "source": "akshare",
                }
            )
        return result

    def get_bars(
        self,
        symbols: list[str],
        start: datetime,
        end: datetime,
        frequency: str = "1d",
    ) -> list[dict[str, Any]]:
        import akshare as ak

        period_map = {"1d": "daily", "1w": "weekly", "1M": "monthly"}
        period = period_map.get(frequency, "daily")
        fetched_at = datetime.now()
        result: list[dict[str, Any]] = []

        for symbol in symbols:
            raw_code = symbol.split(".")[0]
            df = ak.stock_zh_a_hist(
                symbol=raw_code,
                period=period,
                start_date=_fmt_date(start),
                end_date=_fmt_date(end),
                adjust="qfq",
            )
            for _, row in df.iterrows():
                trade_date = row["日期"]
                if isinstance(trade_date, str):
                    trade_date = datetime.strptime(trade_date, "%Y-%m-%d")
                result.append(
                    {
                        "symbol": symbol,
                        "date": trade_date,
                        "open": float(row["开盘"]),
                        "close": float(row["收盘"]),
                        "high": float(row["最高"]),
                        "low": float(row["最低"]),
                        "volume": float(row["成交量"]),
                        "amount": float(row["成交额"]),
                        "frequency": frequency,
                        "fetched_at": fetched_at,
                        "available_at": _market_bar_available_at(trade_date),
                        "source": "akshare",
                    }
                )
        return result

    def get_adjustment_factors(
        self,
        symbols: list[str],
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        import akshare as ak

        fetched_at = datetime.now()
        result: list[dict[str, Any]] = []
        for symbol in symbols:
            raw_code = symbol.split(".")[0]
            df = ak.stock_zh_a_hist(
                symbol=raw_code,
                period="daily",
                start_date=_fmt_date(start),
                end_date=_fmt_date(end),
                adjust="hfq",
            )
            for _, row in df.iterrows():
                trade_date = row["日期"]
                if isinstance(trade_date, str):
                    trade_date = datetime.strptime(trade_date, "%Y-%m-%d")
                result.append(
                    {
                        "symbol": symbol,
                        "date": trade_date,
                        "hfq_close": float(row["收盘"]),
                        "fetched_at": fetched_at,
                        "available_at": _market_bar_available_at(trade_date),
                        "source": "akshare",
                    }
                )
        return result

    def get_financials(
        self,
        symbols: list[str],
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        import akshare as ak

        fetched_at = datetime.now()
        result: list[dict[str, Any]] = []
        for symbol in symbols:
            suffix = "SH" if symbol.endswith(".SH") else "SZ"
            raw_code = f"{suffix}{symbol.split('.')[0]}"
            df = ak.stock_balance_sheet_by_report_em(symbol=raw_code)
            for _, row in df.iterrows():
                report_date = row.get("REPORT_DATE")
                if isinstance(report_date, str):
                    report_date = datetime.strptime(report_date[:10], "%Y-%m-%d")
                if report_date and start <= report_date <= end:
                    published_at = (
                        _parse_optional_date(row.get("NOTICE_DATE"))
                        or _parse_optional_date(row.get("ANN_DATE"))
                        or _parse_optional_date(row.get("公告日期"))
                    )
                    result.append(
                        {
                            "symbol": symbol,
                            "report_date": report_date,
                            "ann_date": published_at,
                            "total_assets": float(row.get("TOTAL_ASSETS", 0) or 0),
                            "total_liabilities": float(
                                row.get("TOTAL_LIABILITIES", 0) or 0
                            ),
                            "total_equity": float(row.get("TOTAL_EQUITY", 0) or 0),
                            "fetched_at": fetched_at,
                            "available_at": published_at or fetched_at,
                            "source": "akshare",
                        }
                    )
        return result

    def get_index_members(self, index_code: str, as_of: datetime) -> list[dict[str, Any]]:
        import akshare as ak

        fetched_at = datetime.now()
        raw_index = index_code.replace("000300", "000300")
        df = ak.index_stock_cons_csindex(symbol=raw_index)
        result: list[dict[str, Any]] = []
        for _, row in df.iterrows():
            raw_symbol = str(row.get("成份券代码", row.get("代码", "")))
            result.append(
                {
                    "symbol": _sz_sh_symbol(raw_symbol),
                    "index_code": index_code,
                    "name": row.get("成份券名称", row.get("名称", "")),
                    "as_of": as_of,
                    "fetched_at": fetched_at,
                    "available_at": as_of,
                    "source": "akshare",
                }
            )
        return result
