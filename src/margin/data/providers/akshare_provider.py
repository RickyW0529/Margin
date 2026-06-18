"""AKShare data provider for A-share quotes, fundamentals, indices and announcement metadata.

This module implements the provider contract defined in specs 01 §3 and the
architecture described in §4.2.1. It covers the work items planned in
plans 0102.1, 0102.3 and 0102.4.
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
    """Convert an AKShare raw symbol into the standard ``000001.SZ`` / ``600000.SH`` format.

    Args:
        raw: The raw symbol string as returned by AKShare. It may already be
            prefixed with ``SH`` or ``SZ`` (e.g. ``SH600000``), or it may be a
            six-digit numeric code.

    Returns:
        A standardized symbol string. Numeric codes starting with ``60``, ``68``
        or ``9`` are mapped to the ``.SH`` suffix, all other six-digit codes are
        mapped to ``.SZ``. If the input does not match any known format it is
        returned unchanged.
    """
    raw = str(raw).strip()
    if raw.startswith(("SH", "SZ")):
        return f"{raw[2:]}.{raw[:2]}"
    if len(raw) == 6:
        if raw.startswith(("60", "68", "9")):
            return f"{raw}.SH"
        return f"{raw}.SZ"
    return raw


def _fmt_date(d: datetime) -> str:
    """Format a datetime as an AKShare-compatible date string.

    Args:
        d: The datetime value to format.

    Returns:
        The date formatted as ``%Y%m%d``.
    """
    return d.strftime("%Y%m%d")


def _market_bar_available_at(trade_date: datetime) -> datetime:
    """Return the availability timestamp for a daily market bar.

    Daily OHLCV bars are considered available after the market closes at 15:00
    on the corresponding trade date.

    Args:
        trade_date: The trade date for which the bar was computed.

    Returns:
        A datetime combining the trade date and 15:00 local time.
    """
    return datetime.combine(trade_date.date(), time(hour=15))


def _parse_optional_date(value: Any) -> datetime | None:
    """Parse an optional date value into a datetime.

    Supports both ``%Y-%m-%d`` and ``%Y%m%d`` formats. Only the first ten
    characters of the string representation are considered.

    Args:
        value: The value to parse. ``None`` and empty strings yield ``None``.

    Returns:
        The parsed datetime, or ``None`` if the value is missing or cannot be
        parsed by any supported format.
    """
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
    """A-share market data provider backed by AKShare.

    AKShare does not require an API token, but callers must respect its rate
    limits. Every public method returns a list of standard-format dictionaries
    that include timing fields such as ``fetched_at`` and ``available_at``.

    Attributes:
        _descriptor: The cached provider descriptor containing metadata,
            capabilities and configuration.
    """

    def __init__(self) -> None:
        """Initialize the provider and build its descriptor."""
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
        """Return the provider descriptor.

        Returns:
            A ``ProviderDescriptor`` describing the provider name, version,
            type, capabilities and configuration.
        """
        return self._descriptor

    def healthcheck(self) -> HealthCheckResult:
        """Check whether AKShare is reachable by fetching the A-share spot snapshot.

        Returns:
            A ``HealthCheckResult`` with status ``HEALTHY`` when the snapshot
            endpoint responds successfully, otherwise ``UNHEALTHY`` with the
            exception message.

        Raises:
            Does not raise exceptions; failures are captured in the returned
            result.
        """
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
        """Fetch the current A-share security list and latest spot prices.

        Args:
            as_of: The reference datetime for the security universe request.
                Currently reserved for interface compatibility; the snapshot
                returned by AKShare reflects the latest available market state.

        Returns:
            A list of dictionaries, each containing ``symbol``, ``name``,
            ``close``, ``fetched_at``, ``available_at`` and ``source``.
        """
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
        """Fetch historical OHLCV bars for the given symbols.

        Args:
            symbols: A list of standard-format symbols such as
                ``["000001.SZ", "600000.SH"]``.
            start: The inclusive start date of the requested range.
            end: The inclusive end date of the requested range.
            frequency: Bar frequency. Supported values are ``"1d"``,
                ``"1w"`` and ``"1M"``. Defaults to ``"1d"``.

        Returns:
            A list of OHLCV bar dictionaries. Each dictionary contains
            ``symbol``, ``date``, ``open``, ``close``, ``high``, ``low``,
            ``volume``, ``amount``, ``frequency``, ``fetched_at``,
            ``available_at`` and ``source``.
        """
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
        """Fetch historical adjustment factors for the given symbols.

        Uses AKShare's ``hfq`` (backward-adjusted) price series and returns the
        adjusted close, which can be used to compute split- and dividend-aware
        cumulative returns.

        Args:
            symbols: A list of standard-format symbols such as
                ``["000001.SZ", "600000.SH"]``.
            start: The inclusive start date of the requested range.
            end: The inclusive end date of the requested range.

        Returns:
            A list of adjustment factor dictionaries. Each dictionary contains
            ``symbol``, ``date``, ``hfq_close``, ``fetched_at``,
            ``available_at`` and ``source``.
        """
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
        """Fetch balance-sheet fundamentals for the given symbols.

        Args:
            symbols: A list of standard-format symbols such as
                ``["000001.SZ", "600000.SH"]``.
            start: The inclusive start report date of the requested range.
            end: The inclusive end report date of the requested range.

        Returns:
            A list of financial statement dictionaries. Each dictionary
            contains ``symbol``, ``report_date``, ``ann_date``,
            ``total_assets``, ``total_liabilities``, ``total_equity``,
            ``fetched_at``, ``available_at`` and ``source``. Announcement dates
            are derived from ``NOTICE_DATE``, ``ANN_DATE`` or ``公告日期`` when
            present; otherwise the fetch timestamp is used as the availability
            time.
        """
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
        """Fetch the current constituent list for the given index.

        Args:
            index_code: The standard index code, e.g. ``"000300.SH"`` for CSI
                300.
            as_of: The reference datetime for the membership request.

        Returns:
            A list of constituent dictionaries. Each dictionary contains
            ``symbol``, ``index_code``, ``name``, ``as_of``, ``fetched_at``,
            ``available_at`` and ``source``.
        """
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
