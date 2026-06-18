"""Tushare data provider for A-share market data.

Implements supplemental market data, financial data, and index membership
queries through the Tushare Pro API. The provider is designed around the
contract defined in spec 01 §3 and architecture §4.2.1, and covers the
planned interfaces in plan 0102.2 / 0102.3 / 0102.4.

Users must configure their own Tushare token, referenced via
``tushare_token`` through SecretManager. Respect Tushare licensing and
rate limits.
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
    """Format a ``datetime`` as an 8-digit date string.

    Args:
        d: The datetime to format.

    Returns:
        The formatted date string in ``YYYYMMDD`` format.
    """
    return d.strftime("%Y%m%d")


def _tushare_symbol(symbol: str) -> str:
    """Convert an internal symbol to the Tushare ts_code format.

    Tushare already uses the ``000001.SZ`` style, so this function is a
    pass-through that preserves compatibility with the rest of the provider.

    Args:
        symbol: Internal symbol, e.g. ``000001.SZ``.

    Returns:
        The same symbol in Tushare format.
    """
    return symbol


def _market_bar_available_at(trade_date: datetime) -> datetime:
    """Compute the earliest availability time for a daily market bar.

    Daily OHLCV bars are typically finalized after the market closes at
    15:00.

    Args:
        trade_date: The trading date for which the bar is available.

    Returns:
        A datetime combining the trading date with 15:00.
    """
    return datetime.combine(trade_date.date(), time(hour=15))


def _next_market_open_after(value: datetime) -> datetime:
    """Return the next market open after a given datetime.

    Financial announcements released after market close become actionable
    at the next market open (09:30).

    Args:
        value: The reference datetime.

    Returns:
        The next calendar day's market open at 09:30.
    """
    return datetime.combine((value + timedelta(days=1)).date(), time(hour=9, minute=30))


class TushareProvider(BaseProvider):
    """A-share market data provider backed by the Tushare Pro API.

    This provider exposes securities metadata, daily bars, adjustment
    factors, financial indicators, and index constituent weights. The
    Tushare token is resolved externally via SecretManager and injected
    through :meth:`configure_secrets` or :meth:`set_token`.

    Attributes:
        _token: The Tushare API token, or ``None`` if not yet configured.
        _pro: The lazily-initialized Tushare ``pro_api`` client.
        _descriptor: Provider metadata and capabilities descriptor.
    """

    def __init__(self, token: str | None = None) -> None:
        """Initialize a new ``TushareProvider`` instance.

        Args:
            token: Optional Tushare API token. When omitted, the token
                must be injected later via :meth:`set_token` or
                :meth:`configure_secrets`.
        """
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
        """Return the provider descriptor.

        Returns:
            A :class:`ProviderDescriptor` describing this provider's name,
            version, type, capabilities, and secret references.
        """
        return self._descriptor

    def _ensure_pro(self) -> Any:
        """Lazily initialize and return the Tushare Pro API client.

        If a token has not been set, an empty string is passed to
        ``pro_api``, which relies on the environment or prior global
        configuration.

        Returns:
            The initialized Tushare Pro API client.

        Raises:
            Exception: If the ``tushare`` package cannot be imported or the
                client fails to initialize.
        """
        if self._pro is not None:
            return self._pro
        import tushare as ts

        self._pro = ts.pro_api(token=self._token or "")
        return self._pro

    def set_token(self, token: str) -> None:
        """Set or update the Tushare API token.

        Resetting the token clears any previously initialized API client so
        the next call to :meth:`_ensure_pro` creates a fresh client.

        Args:
            token: The Tushare API token string.
        """
        self._token = token
        self._pro = None

    def configure_secrets(self, secrets: dict[str, str]) -> None:
        """Inject resolved secret references from the provider registry.

        Args:
            secrets: Mapping of secret reference names to resolved values.
                The ``tushare_token`` key is used when present.
        """
        token = secrets.get("tushare_token")
        if token:
            self.set_token(token)

    def healthcheck(self) -> HealthCheckResult:
        """Verify connectivity to Tushare by calling ``stock_basic``.

        Returns:
            A :class:`HealthCheckResult` indicating ``HEALTHY`` if the test
            request succeeds, or ``UNHEALTHY`` with the error message
            otherwise.

        Note:
            This method does not raise exceptions; errors are captured in
            the returned result.
        """
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
        """Fetch the list of currently listed A-share securities.

        Args:
            as_of: Reference datetime for the request. The underlying data
                is the latest available from Tushare.

        Returns:
            A list of dictionaries, each containing ``symbol``, ``name``,
            ``industry``, ``market``, ``list_date``, ``fetched_at``,
            ``available_at``, and ``source``.

        Raises:
            Exception: If the Tushare request fails.
        """
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
        """Fetch daily OHLCV bars for the requested symbols.

        Args:
            symbols: List of internal symbols to fetch.
            start: Start of the requested date range (inclusive).
            end: End of the requested date range (inclusive).
            frequency: Bar frequency; defaults to ``"1d"``. Currently only
                daily bars are supported.

        Returns:
            A list of dictionaries, each containing ``symbol``, ``date``,
            ``open``, ``close``, ``high``, ``low``, ``volume``, ``amount``,
            ``frequency``, ``fetched_at``, ``available_at``, and ``source``.

        Raises:
            Exception: If the Tushare request fails or the response cannot
                be parsed.
        """
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
        """Fetch adjustment factors for the requested symbols.

        Args:
            symbols: List of internal symbols to fetch.
            start: Start of the requested date range (inclusive).
            end: End of the requested date range (inclusive).

        Returns:
            A list of dictionaries, each containing ``symbol``, ``date``,
            ``adj_factor``, ``fetched_at``, ``available_at``, and ``source``.

        Raises:
            Exception: If the Tushare request fails or the response cannot
                be parsed.
        """
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
        """Fetch financial indicators for the requested symbols.

        Args:
            symbols: List of internal symbols to fetch.
            start: Start of the requested report/announcement date range
                (inclusive).
            end: End of the requested report/announcement date range
                (inclusive).

        Returns:
            A list of dictionaries, each containing ``symbol``,
            ``report_date``, ``ann_date``, ``roe``, ``eps``,
            ``gross_profit_margin``, ``fetched_at``, ``available_at``, and
            ``source``.

        Raises:
            Exception: If the Tushare request fails or the response cannot
                be parsed.
        """
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
        """Fetch index constituent weights as of a given date.

        Args:
            index_code: The Tushare index code, e.g. ``000001.SH``.
            as_of: The reference date for constituent weights.

        Returns:
            A list of dictionaries, each containing ``symbol``,
            ``index_code``, ``weight``, ``as_of``, ``fetched_at``,
            ``available_at``, and ``source``.

        Raises:
            Exception: If the Tushare request fails or the response cannot
                be parsed.
        """
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
