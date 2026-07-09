"""Field standardization module — unify multi-source external data into a standard format.

Corresponds to specs 01 §2 / §4 and architecture §4.3 (data standardization flow).
Corresponds to all plans 0103 work items:
  0103.1 Field mapping and code mapping
  0103.2 Unit and currency unification
  0103.3 Time standardization
  0103.4 Standard data event publication

Standardization flow (architecture §4.3):
  External data → Field mapping → Code mapping → Unit/currency unification
  → Time standardization → Quality validation → Standard data event
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# 0103.1 Code mapping
# ---------------------------------------------------------------------------


class Exchange(StrEnum):
    """A-share stock exchanges.."""

    SH = "SH"
    SZ = "SZ"


def normalize_symbol(raw: str) -> str:
    """Normalize various symbol formats to ``<code>.<EXCHANGE>`` form.

    Args:
        raw: str: .

    Returns:
        str: .
    """
    raw = str(raw).strip().upper()

    if "." in raw:
        code, exchange = raw.split(".", 1)
        return f"{code}.{exchange.upper()}"

    if raw.startswith(("SH", "SZ")):
        return f"{raw[2:]}.{raw[:2]}"

    if len(raw) == 6 and raw.isdigit():
        if raw.startswith(("60", "68", "90", "11", "13")):
            return f"{raw}.SH"
        return f"{raw}.SZ"

    return raw


def symbol_components(symbol: str) -> tuple[str, str]:
    """Split a standardized symbol into its code and exchange components.

    Args:
        symbol: str: .

    Returns:
        tuple[str, str]: .
    """
    if "." not in symbol:
        raise ValueError(f"Invalid symbol format: {symbol}")
    code, exchange = symbol.split(".", 1)
    return code, exchange.upper()


# ---------------------------------------------------------------------------
# 0103.1 Field mapping
# ---------------------------------------------------------------------------


class DataDomain(StrEnum):
    """Data domains in the standardization layer (architecture §4.1).."""

    MARKET_BAR = "market_bar"
    FINANCIAL = "financial"
    SECURITY_META = "security_meta"
    INDEX_MEMBER = "index_member"
    ADJUSTMENT_FACTOR = "adjustment_factor"
    CORPORATE_ACTION = "corporate_action"


class FieldMapping(BaseModel):
    """Mapping rule for a single field from a source to the standard schema.."""

    source_field: str
    target_field: str
    transform: str | None = None
    unit_factor: float = 1.0

    model_config = {"frozen": True}


FIELD_MAPPINGS: dict[DataDomain, dict[str, FieldMapping]] = {
    DataDomain.MARKET_BAR: {
        "代码": FieldMapping(
            source_field="代码", target_field="symbol", transform="normalize_symbol"
        ),
        "开盘": FieldMapping(source_field="开盘", target_field="open"),
        "收盘": FieldMapping(source_field="收盘", target_field="close"),
        "最高": FieldMapping(source_field="最高", target_field="high"),
        "最低": FieldMapping(source_field="最低", target_field="low"),
        "成交量": FieldMapping(source_field="成交量", target_field="volume"),
        "成交额": FieldMapping(source_field="成交额", target_field="amount"),
    },
}
"""Default field mappings from external source fields to the standard schema.

The outer dictionary is keyed by :class:`DataDomain`. Each inner dictionary maps
a source field name to a :class:`FieldMapping` rule describing the target field,
optional transform, and unit conversion factor.
"""


# ---------------------------------------------------------------------------
# 0103.2 Unit and currency unification
# ---------------------------------------------------------------------------


class UnitConverter:
    """Unify units and currency for A-share data.."""

    CURRENCY = "CNY"

    @staticmethod
    def convert_amount(value: float, source_unit: str = "yuan") -> float:
        """Convert a monetary amount to yuan.

        Args:
            value: float: .
            source_unit: str: .

        Returns:
            float: .
        """
        if source_unit == "qian_yuan":
            return value * 1000.0
        if source_unit == "wan_yuan":
            return value * 10000.0
        if source_unit == "yi_yuan":
            return value * 100000000.0
        return value

    @staticmethod
    def convert_volume(value: float, source_unit: str = "gu") -> float:
        """Convert trading volume to shares.

        Args:
            value: float: .
            source_unit: str: .

        Returns:
            float: .
        """
        if source_unit == "shou":
            return value * 100.0
        return value


# ---------------------------------------------------------------------------
# 0103.3 Time standardization
# ---------------------------------------------------------------------------


class TimeStandardizer:
    """Standardize timestamps, producing the five point-in-time fields.."""

    @staticmethod
    def parse_date(value: Any) -> datetime | None:
        """Parse a value in multiple date formats into a ``datetime``.

        Args:
            value: Any: .

        Returns:
            datetime | None: .
        """
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            return value

        value_str = str(value).strip()

        formats = [
            "%Y-%m-%d",
            "%Y-%m-%d %H:%M:%S",
            "%Y%m%d",
            "%Y%m%d %H:%M:%S",
            "%Y/%m/%d",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(value_str[:19], fmt)
            except ValueError:
                continue
        return None

    @staticmethod
    def to_pit_fields(
        event_at: datetime | None = None,
        published_at: datetime | None = None,
        available_at: datetime | None = None,
        fetched_at: datetime | None = None,
        revised_at: datetime | None = None,
    ) -> dict[str, datetime]:
        """Generate the full set of point-in-time fields.

        Args:
            event_at: datetime | None: .
            published_at: datetime | None: .
            available_at: datetime | None: .
            fetched_at: datetime | None: .
            revised_at: datetime | None: .

        Returns:
            dict[str, datetime]: .
        """
        now = datetime.now()
        return {
            "event_at": event_at or now,
            "published_at": published_at or event_at or now,
            "available_at": available_at or published_at or event_at or now,
            "fetched_at": fetched_at or now,
            "revised_at": revised_at,
        }


def market_bar_available_at(trade_date: datetime) -> datetime:
    """Return the earliest usable timestamp for a daily A-share bar.

    Args:
        trade_date: datetime: .

    Returns:
        datetime: .
    """
    return datetime.combine(trade_date.date(), time(hour=15))


def next_market_open_after(value: datetime) -> datetime:
    """Return a conservative availability timestamp for an untimed announcement.

    Args:
        value: datetime: .

    Returns:
        datetime: .
    """
    return datetime.combine((value + timedelta(days=1)).date(), time(hour=9, minute=30))


# ---------------------------------------------------------------------------
# 0103.4 Standard data event
# ---------------------------------------------------------------------------


class StandardDataEvent(BaseModel):
    """Standard data event published after standardization (architecture §4.3).."""

    domain: DataDomain
    symbol: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    event_at: datetime
    published_at: datetime
    available_at: datetime
    fetched_at: datetime
    revised_at: datetime | None = None
    source: str
    mapping_version: str = "v1"

    model_config = {"frozen": True}


class Standardizer:
    """Convert raw data returned by an external provider into standard data events.."""

    def __init__(self, mapping_version: str = "v1") -> None:
        """Initialize a ``Standardizer``.

        Args:
            mapping_version: str: .

        Returns:
            None: .
        """
        self._mapping_version = mapping_version

    def standardize_bars(
        self,
        raw_records: list[dict[str, Any]],
        source: str,
    ) -> list[StandardDataEvent]:
        """Standardize market bar (OHLCV) records.

        Args:
            raw_records: list[dict[str, Any]]: .
            source: str: .

        Returns:
            list[StandardDataEvent]: .
        """
        events: list[StandardDataEvent] = []
        for record in raw_records:
            symbol = normalize_symbol(record.get("symbol", ""))
            event_at = TimeStandardizer.parse_date(record.get("date"))
            available_at = TimeStandardizer.parse_date(record.get("available_at"))
            if available_at is None and event_at is not None:
                available_at = market_bar_available_at(event_at)
            pit = TimeStandardizer.to_pit_fields(
                event_at=event_at,
                available_at=available_at,
                fetched_at=TimeStandardizer.parse_date(record.get("fetched_at")),
            )

            data = {
                "open": float(record.get("open", 0) or 0),
                "close": float(record.get("close", 0) or 0),
                "high": float(record.get("high", 0) or 0),
                "low": float(record.get("low", 0) or 0),
                "volume": UnitConverter.convert_volume(
                    float(record.get("volume", 0) or 0),
                    str(record.get("volume_unit", "gu")),
                ),
                "amount": UnitConverter.convert_amount(
                    float(record.get("amount", 0) or 0),
                    str(record.get("amount_unit", "yuan")),
                ),
                "frequency": record.get("frequency", "1d"),
            }

            events.append(
                StandardDataEvent(
                    domain=DataDomain.MARKET_BAR,
                    symbol=symbol,
                    data=data,
                    source=source,
                    mapping_version=self._mapping_version,
                    **pit,
                )
            )
        return events

    def standardize_securities(
        self,
        raw_records: list[dict[str, Any]],
        source: str,
    ) -> list[StandardDataEvent]:
        """Standardize security metadata records.

        Args:
            raw_records: list[dict[str, Any]]: .
            source: str: .

        Returns:
            list[StandardDataEvent]: .
        """
        events: list[StandardDataEvent] = []
        for record in raw_records:
            symbol = normalize_symbol(record.get("symbol", ""))
            fetched_at = TimeStandardizer.parse_date(record.get("fetched_at"))
            pit = TimeStandardizer.to_pit_fields(
                fetched_at=fetched_at,
                available_at=TimeStandardizer.parse_date(record.get("available_at")),
            )

            data = {
                "name": record.get("name", ""),
                "industry": record.get("industry", ""),
                "market": record.get("market", ""),
                "list_date": record.get("list_date"),
            }

            events.append(
                StandardDataEvent(
                    domain=DataDomain.SECURITY_META,
                    symbol=symbol,
                    data=data,
                    source=source,
                    mapping_version=self._mapping_version,
                    **pit,
                )
            )
        return events

    def standardize_financials(
        self,
        raw_records: list[dict[str, Any]],
        source: str,
    ) -> list[StandardDataEvent]:
        """Standardize financial report records.

        Args:
            raw_records: list[dict[str, Any]]: .
            source: str: .

        Returns:
            list[StandardDataEvent]: .
        """
        events: list[StandardDataEvent] = []
        for record in raw_records:
            symbol = normalize_symbol(record.get("symbol", ""))
            report_date = TimeStandardizer.parse_date(record.get("report_date"))
            published_at = TimeStandardizer.parse_date(record.get("ann_date"))
            fetched_at = TimeStandardizer.parse_date(record.get("fetched_at"))
            available_at = TimeStandardizer.parse_date(record.get("available_at"))
            if available_at is None and published_at is not None:
                available_at = next_market_open_after(published_at)
            if available_at is None:
                available_at = fetched_at
            pit = TimeStandardizer.to_pit_fields(
                event_at=report_date,
                published_at=published_at,
                available_at=available_at,
                fetched_at=fetched_at,
            )

            data: dict[str, Any] = {}
            for key in (
                "total_assets",
                "total_liabilities",
                "total_equity",
                "roe",
                "eps",
                "gross_profit_margin",
                "revenue",
                "net_profit",
            ):
                if key in record and record[key] is not None:
                    data[key] = float(record[key])

            events.append(
                StandardDataEvent(
                    domain=DataDomain.FINANCIAL,
                    symbol=symbol,
                    data=data,
                    source=source,
                    mapping_version=self._mapping_version,
                    **pit,
                )
            )
        return events

    def standardize_index_members(
        self,
        raw_records: list[dict[str, Any]],
        source: str,
    ) -> list[StandardDataEvent]:
        """Standardize index constituent records.

        Args:
            raw_records: list[dict[str, Any]]: .
            source: str: .

        Returns:
            list[StandardDataEvent]: .
        """
        events: list[StandardDataEvent] = []
        for record in raw_records:
            symbol = normalize_symbol(record.get("symbol", ""))
            as_of = TimeStandardizer.parse_date(record.get("as_of"))
            pit = TimeStandardizer.to_pit_fields(
                event_at=as_of,
                available_at=TimeStandardizer.parse_date(record.get("available_at")) or as_of,
                fetched_at=TimeStandardizer.parse_date(record.get("fetched_at")),
            )

            data = {
                "index_code": record.get("index_code", ""),
                "name": record.get("name", ""),
                "weight": float(record.get("weight", 0) or 0),
            }

            events.append(
                StandardDataEvent(
                    domain=DataDomain.INDEX_MEMBER,
                    symbol=symbol,
                    data=data,
                    source=source,
                    mapping_version=self._mapping_version,
                    **pit,
                )
            )
        return events
