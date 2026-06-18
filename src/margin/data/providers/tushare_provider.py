"""Tushare 数据 Provider — A 股行情、财务、指数成分等补充数据。

对应 spec 01 §3 接口契约、架构 §4.2.1。
对应 plan 0102.2 / 0102.3 / 0102.4。

用户自行配置 token（走 SecretManager 引用），遵守 Tushare 授权与频率限制。
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any

from margin.core.provider import (
    BaseProvider,
    HealthCheckResult,
    ProviderDescriptor,
    ProviderStatus,
    ProviderType,
)


def _fmt_date(d: datetime) -> str:
    return d.strftime("%Y%m%d")


def _tushare_symbol(symbol: str) -> str:
    """标准 symbol ``000001.SZ`` → Tushare 口径 ``000001.SZ``（Tushare 本身用此格式）。"""
    return symbol


def _market_bar_available_at(trade_date: datetime) -> datetime:
    return datetime.combine(trade_date.date(), time(hour=15))


def _next_market_open_after(value: datetime) -> datetime:
    return datetime.combine((value + timedelta(days=1)).date(), time(hour=9, minute=30))


class TushareProvider(BaseProvider):
    """基于 Tushare pro_api 的 A 股市场数据 Provider。

    token 走 SecretManager 引用 ``tushare_token``，不明文存配置。
    """

    def __init__(self, token: str | None = None) -> None:
        self._token = token
        self._pro = None
        self._descriptor = ProviderDescriptor(
            name="tushare",
            version="1.0.0",
            provider_type=ProviderType.MARKET_DATA,
            capabilities=[
                "get_securities",
                "get_bars",
                "get_adjustment_factors",
                "get_financials",
                "get_index_members",
            ],
            secret_refs=["tushare_token"],
            config={"license": "用户自行配置 token", "limits": "遵守 tushare 频率限制"},
        )

    @property
    def descriptor(self) -> ProviderDescriptor:
        return self._descriptor

    def _ensure_pro(self) -> Any:
        """惰性初始化 tushare pro_api，token 从构造或 SecretManager 注入。"""
        if self._pro is not None:
            return self._pro
        import tushare as ts

        self._pro = ts.pro_api(token=self._token or "")
        return self._pro

    def set_token(self, token: str) -> None:
        """设置 token（由 Registry 在 resolve_secrets 后注入）。"""
        self._token = token
        self._pro = None

    def configure_secrets(self, secrets: dict[str, str]) -> None:
        """Inject resolved Secret refs from ProviderRegistry."""
        token = secrets.get("tushare_token")
        if token:
            self.set_token(token)

    def healthcheck(self) -> HealthCheckResult:
        try:
            pro = self._ensure_pro()
            pro.stock_basic(exchange="", list_status="L", limit=1)
            return HealthCheckResult(
                provider_name="tushare",
                status=ProviderStatus.HEALTHY,
                checked_at=datetime.now(),
                message="stock_basic ok",
            )
        except Exception as exc:
            return HealthCheckResult(
                provider_name="tushare",
                status=ProviderStatus.UNHEALTHY,
                checked_at=datetime.now(),
                message=str(exc),
            )

    def get_securities(self, as_of: datetime) -> list[dict[str, Any]]:
        pro = self._ensure_pro()
        df = pro.stock_basic(exchange="", list_status="L")
        fetched_at = datetime.now()
        result: list[dict[str, Any]] = []
        for _, row in df.iterrows():
            result.append(
                {
                    "symbol": row["ts_code"],
                    "name": row["name"],
                    "industry": row.get("industry", ""),
                    "market": row.get("market", ""),
                    "list_date": row.get("list_date", ""),
                    "fetched_at": fetched_at,
                    "available_at": fetched_at,
                    "source": "tushare",
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
        pro = self._ensure_pro()
        fetched_at = datetime.now()
        result: list[dict[str, Any]] = []
        for symbol in symbols:
            ts_code = _tushare_symbol(symbol)
            df = pro.daily(
                ts_code=ts_code,
                start_date=_fmt_date(start),
                end_date=_fmt_date(end),
            )
            for _, row in df.iterrows():
                trade_date_str = str(row["trade_date"])
                trade_date = datetime.strptime(trade_date_str, "%Y%m%d")
                result.append(
                    {
                        "symbol": ts_code,
                        "date": trade_date,
                        "open": float(row["open"]),
                        "close": float(row["close"]),
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "volume": float(row["vol"]) * 100.0,
                        "amount": float(row["amount"]) * 1000.0,
                        "frequency": frequency,
                        "fetched_at": fetched_at,
                        "available_at": _market_bar_available_at(trade_date),
                        "source": "tushare",
                    }
                )
        return result

    def get_adjustment_factors(
        self,
        symbols: list[str],
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        pro = self._ensure_pro()
        fetched_at = datetime.now()
        result: list[dict[str, Any]] = []
        for symbol in symbols:
            ts_code = _tushare_symbol(symbol)
            df = pro.adj_factor(
                ts_code=ts_code,
                start_date=_fmt_date(start),
                end_date=_fmt_date(end),
            )
            for _, row in df.iterrows():
                trade_date_str = str(row["trade_date"])
                trade_date = datetime.strptime(trade_date_str, "%Y%m%d")
                result.append(
                    {
                        "symbol": ts_code,
                        "date": trade_date,
                        "adj_factor": float(row["adj_factor"]),
                        "fetched_at": fetched_at,
                        "available_at": _market_bar_available_at(trade_date),
                        "source": "tushare",
                    }
                )
        return result

    def get_financials(
        self,
        symbols: list[str],
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        pro = self._ensure_pro()
        fetched_at = datetime.now()
        result: list[dict[str, Any]] = []
        for symbol in symbols:
            ts_code = _tushare_symbol(symbol)
            df = pro.fina_indicator(
                ts_code=ts_code,
                start_date=_fmt_date(start),
                end_date=_fmt_date(end),
            )
            for _, row in df.iterrows():
                ann_date_str = str(row.get("ann_date", row.get("end_date", "")))
                if ann_date_str:
                    ann_date = datetime.strptime(ann_date_str, "%Y%m%d")
                else:
                    ann_date = fetched_at
                end_date_str = str(row.get("end_date", ann_date_str))
                if end_date_str:
                    report_date = datetime.strptime(end_date_str, "%Y%m%d")
                else:
                    report_date = ann_date
                result.append(
                    {
                        "symbol": ts_code,
                        "report_date": report_date,
                        "ann_date": ann_date,
                        "roe": float(row.get("roe", 0) or 0),
                        "eps": float(row.get("eps", 0) or 0),
                        "gross_profit_margin": float(
                            row.get("gross_profit_margin", 0) or 0
                        ),
                        "fetched_at": fetched_at,
                        "available_at": _next_market_open_after(ann_date),
                        "source": "tushare",
                    }
                )
        return result

    def get_index_members(self, index_code: str, as_of: datetime) -> list[dict[str, Any]]:
        pro = self._ensure_pro()
        fetched_at = datetime.now()
        df = pro.index_weight(index_code=index_code, start_date=_fmt_date(as_of))
        result: list[dict[str, Any]] = []
        for _, row in df.iterrows():
            result.append(
                {
                    "symbol": row["con_code"],
                    "index_code": index_code,
                    "weight": float(row.get("weight", 0) or 0),
                    "as_of": as_of,
                    "fetched_at": fetched_at,
                    "available_at": as_of,
                    "source": "tushare",
                }
            )
        return result
