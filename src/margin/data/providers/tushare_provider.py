"""Tushare data provider for A-share market data.

Implements supplemental market data, financial data, and index membership
queries through the Tushare Pro API. The provider is designed around the
contract defined in specs 01 §3 and architecture §4.2.1, and covers the
planned interfaces in plans 0102.2 / 0102.3 / 0102.4.

Users must configure their own Tushare token, referenced via
``tushare_token`` through SecretManager. Respect Tushare licensing and
rate limits.
"""

from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta
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


def _optional_float(value: Any) -> float | None:
    """Return a finite numeric provider value or ``None`` when unavailable."""
    if value is None or value == "":
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _ratio(value: Any) -> float | None:
    """Normalize Tushare percentage fields to decimal ratios."""
    numeric = _optional_float(value)
    if numeric is None:
        return None
    return numeric / 100.0 if abs(numeric) > 1 else numeric


def _calendar_days(start: datetime, end: datetime) -> list[datetime]:
    """Return inclusive calendar days for bounded cross-section requests."""
    if end < start:
        return []
    days = (end.date() - start.date()).days
    return [
        datetime.combine(start.date() + timedelta(days=offset), time.min)
        for offset in range(days + 1)
    ]


def _map_bar_row(
    row: Any,
    *,
    ts_code: str,
    fetched_at: datetime,
    frequency: str,
) -> dict[str, Any]:
    """Map one Tushare ``daily`` row to the canonical market-bar contract."""
    trade_date = datetime.strptime(str(row["trade_date"]), "%Y%m%d")
    return {
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


def _map_adjustment_row(
    row: Any,
    *,
    ts_code: str,
    fetched_at: datetime,
) -> dict[str, Any]:
    """Map one Tushare ``adj_factor`` row."""
    trade_date = datetime.strptime(str(row["trade_date"]), "%Y%m%d")
    return {
        "symbol": ts_code,
        "date": trade_date,
        "adj_factor": float(row["adj_factor"]),
        "fetched_at": fetched_at,
        "available_at": _market_bar_available_at(trade_date),
        "source": "tushare",
    }


def _map_financial_row(
    row: Any,
    *,
    ts_code: str,
    fetched_at: datetime,
) -> dict[str, Any]:
    """Map one Tushare ``fina_indicator`` row to canonical factor names."""
    ann_date_value = row.get("ann_date") or row.get("end_date")
    ann_date = (
        datetime.strptime(str(ann_date_value), "%Y%m%d")
        if ann_date_value
        else fetched_at
    )
    report_date_value = row.get("end_date") or ann_date_value
    report_date = (
        datetime.strptime(str(report_date_value), "%Y%m%d")
        if report_date_value
        else ann_date
    )
    gross_margin = row.get("grossprofit_margin")
    if gross_margin is None:
        gross_margin = row.get("gross_profit_margin")
    roe = _ratio(row.get("roe"))
    gross_margin_ratio = _ratio(gross_margin)
    return {
        "symbol": ts_code,
        "report_date": report_date,
        "ann_date": ann_date,
        "roe": roe,
        "roe_ttm": roe,
        "eps": _optional_float(row.get("eps")),
        "gross_profit_margin": gross_margin_ratio,
        "gross_margin_ttm": gross_margin_ratio,
        "net_margin_ttm": _ratio(row.get("netprofit_margin")),
        "liability_ratio": _ratio(row.get("debt_to_assets")),
        "revenue_yoy": _ratio(row.get("tr_yoy")),
        "profit_yoy": _ratio(row.get("netprofit_yoy")),
        "fetched_at": fetched_at,
        "available_at": _next_market_open_after(ann_date),
        "source": "tushare",
    }


def _parse_tushare_date(value: Any) -> date | None:
    """Parse an optional Tushare YYYYMMDD value."""
    if value is None or value == "":
        return None
    try:
        return datetime.strptime(str(value), "%Y%m%d").date()
    except ValueError:
        return None


def _latest_income_profit_by_period(
    rows: list[Any],
) -> dict[tuple[str, str], float]:
    """Return the latest-announced raw ``n_income_attr_p`` per period.

    The raw per-period net profit attributable to parent is landed as a
    canonical fact so the Feature Mart ETL can derive prior annual profits
    (``net_profit_y1``/``net_profit_y2``) with PIT safety and without relying
    on provider-time derivation. ``net_profit_ttm`` is intentionally not
    derived here: it is not consumed by any factor and deriving it inline
    was the source of unstable, unrecoverable gaps.
    """
    latest_by_period: dict[tuple[str, date], tuple[date, float]] = {}
    for row in rows:
        ts_code = str(row.get("ts_code", ""))
        end_date = _parse_tushare_date(row.get("end_date"))
        profit = _optional_float(row.get("n_income_attr_p"))
        if not ts_code or end_date is None or profit is None:
            continue
        announced = (
            _parse_tushare_date(row.get("f_ann_date"))
            or _parse_tushare_date(row.get("ann_date"))
            or end_date
        )
        key = (ts_code, end_date)
        current = latest_by_period.get(key)
        if current is None or announced >= current[0]:
            latest_by_period[key] = (announced, profit)
    return {
        (ts_code, end_date.strftime("%Y%m%d")): profit
        for (ts_code, end_date), (_, profit) in latest_by_period.items()
    }


def _map_valuation_row(
    row: Any,
    *,
    ts_code: str,
    fetched_at: datetime,
) -> dict[str, Any]:
    """Map one Tushare ``daily_basic`` row."""
    trade_date = datetime.strptime(str(row["trade_date"]), "%Y%m%d")
    total_mv = _optional_float(row.get("total_mv"))
    return {
        "symbol": ts_code,
        "trade_date": trade_date,
        "pe_ttm": _optional_float(row.get("pe_ttm")),
        "pb": _optional_float(row.get("pb")),
        "ps": _optional_float(row.get("ps_ttm")),
        "dividend_yield": _ratio(row.get("dv_ttm")),
        "turnover_rate": _ratio(row.get("turnover_rate")),
        "market_cap": total_mv * 1000.0 if total_mv is not None else None,
        "fetched_at": fetched_at,
        "available_at": _market_bar_available_at(trade_date),
        "source": "tushare",
    }


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

    def __init__(self, token: str | None = None, http_url: str | None = None) -> None:
        """Initialize a new ``TushareProvider`` instance.

        Args:
            token: Optional Tushare API token. When omitted, the token
                must be injected later via :meth:`set_token` or
                :meth:`configure_secrets`.
            http_url: Optional Tushare-compatible API endpoint URL. This is
                useful for licensed proxies such as TeaJoin.
        """
        self._token = token
        self._http_url = http_url
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
                "get_valuations",
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
        if self._http_url:
            self._pro._DataApi__http_url = self._http_url
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
        if len(symbols) > 20:
            allowed = {_tushare_symbol(symbol) for symbol in symbols}
            for trade_day in _calendar_days(start, end):
                df = pro.daily(trade_date=_fmt_date(trade_day))
                for _, row in df.iterrows():
                    ts_code = str(row.get("ts_code", ""))
                    if ts_code not in allowed:
                        continue
                    result.append(
                        _map_bar_row(
                            row,
                            ts_code=ts_code,
                            fetched_at=fetched_at,
                            frequency=frequency,
                        )
                    )
            return result
        for symbol in symbols:
            ts_code = _tushare_symbol(symbol)
            df = pro.daily(
                ts_code=ts_code,
                start_date=_fmt_date(start),
                end_date=_fmt_date(end),
            )
            for _, row in df.iterrows():
                result.append(
                    _map_bar_row(
                        row,
                        ts_code=ts_code,
                        fetched_at=fetched_at,
                        frequency=frequency,
                    )
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
        if len(symbols) > 20:
            allowed = {_tushare_symbol(symbol) for symbol in symbols}
            for trade_day in _calendar_days(start, end):
                df = pro.adj_factor(trade_date=_fmt_date(trade_day))
                for _, row in df.iterrows():
                    ts_code = str(row.get("ts_code", ""))
                    if ts_code not in allowed:
                        continue
                    result.append(
                        _map_adjustment_row(
                            row,
                            ts_code=ts_code,
                            fetched_at=fetched_at,
                        )
                    )
            return result
        for symbol in symbols:
            ts_code = _tushare_symbol(symbol)
            df = pro.adj_factor(
                ts_code=ts_code,
                start_date=_fmt_date(start),
                end_date=_fmt_date(end),
            )
            for _, row in df.iterrows():
                result.append(
                    _map_adjustment_row(
                        row,
                        ts_code=ts_code,
                        fetched_at=fetched_at,
                    )
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
        indicator_rows: list[Any] = []
        income_rows: list[Any] = []
        indicator_fields = (
            "ts_code,ann_date,end_date,roe,eps,grossprofit_margin,"
            "netprofit_margin,debt_to_assets,tr_yoy,netprofit_yoy"
        )
        income_fields = (
            "ts_code,ann_date,f_ann_date,end_date,report_type,"
            "n_income_attr_p"
        )
        if len(symbols) > 20:
            allowed = {_tushare_symbol(symbol) for symbol in symbols}
            offset = 0
            limit = 5000
            while True:
                df = pro.fina_indicator(
                    start_date=_fmt_date(start),
                    end_date=_fmt_date(end),
                    offset=offset,
                    limit=limit,
                    fields=indicator_fields,
                )
                rows = list(df.iterrows())
                for _, row in rows:
                    ts_code = str(row.get("ts_code", ""))
                    if ts_code in allowed:
                        indicator_rows.append(row)
                if len(rows) < limit:
                    break
                offset += limit
            offset = 0
            while True:
                df = pro.income(
                    start_date=_fmt_date(start),
                    end_date=_fmt_date(end),
                    offset=offset,
                    limit=limit,
                    fields=income_fields,
                )
                rows = list(df.iterrows())
                income_rows.extend(
                    row
                    for _, row in rows
                    if str(row.get("ts_code", "")) in allowed
                )
                if len(rows) < limit:
                    break
                offset += limit
        else:
            for symbol in symbols:
                ts_code = _tushare_symbol(symbol)
                df = pro.fina_indicator(
                    ts_code=ts_code,
                    start_date=_fmt_date(start),
                    end_date=_fmt_date(end),
                )
                for _, row in df.iterrows():
                    if not row.get("ts_code"):
                        row = dict(row)
                        row["ts_code"] = ts_code
                    indicator_rows.append(row)
                income_df = pro.income(
                    ts_code=ts_code,
                    start_date=_fmt_date(start),
                    end_date=_fmt_date(end),
                    fields=income_fields,
                )
                for _, row in income_df.iterrows():
                    if not row.get("ts_code"):
                        row = dict(row)
                        row["ts_code"] = ts_code
                    income_rows.append(row)

        income_profit_by_period = _latest_income_profit_by_period(income_rows)
        result: list[dict[str, Any]] = []
        for row in indicator_rows:
            ts_code = str(row.get("ts_code", ""))
            mapped = _map_financial_row(
                row,
                ts_code=ts_code,
                fetched_at=fetched_at,
            )
            period_key = str(row.get("end_date") or "")
            raw_profit = income_profit_by_period.get((ts_code, period_key))
            if raw_profit is not None:
                mapped["n_income_attr_p"] = raw_profit
            result.append(mapped)
        return result

    def get_valuations(
        self,
        symbols: list[str],
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        """Fetch PIT-safe daily valuation metrics from ``daily_basic``."""
        pro = self._ensure_pro()
        fetched_at = datetime.now()
        result: list[dict[str, Any]] = []
        fields = (
            "ts_code,trade_date,turnover_rate,pe_ttm,pb,ps_ttm,"
            "dv_ttm,total_mv"
        )
        if len(symbols) > 20:
            allowed = {_tushare_symbol(symbol) for symbol in symbols}
            for trade_day in _calendar_days(start, end):
                df = pro.daily_basic(
                    trade_date=_fmt_date(trade_day),
                    fields=fields,
                )
                for _, row in df.iterrows():
                    ts_code = str(row.get("ts_code", ""))
                    if ts_code not in allowed:
                        continue
                    result.append(
                        _map_valuation_row(
                            row,
                            ts_code=ts_code,
                            fetched_at=fetched_at,
                        )
                    )
            return result
        for symbol in symbols:
            ts_code = _tushare_symbol(symbol)
            df = pro.daily_basic(
                ts_code=ts_code,
                start_date=_fmt_date(start),
                end_date=_fmt_date(end),
                fields=fields,
            )
            for _, row in df.iterrows():
                result.append(
                    _map_valuation_row(
                        row,
                        ts_code=ts_code,
                        fetched_at=fetched_at,
                    )
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
