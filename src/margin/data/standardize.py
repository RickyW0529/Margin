"""字段标准化模块 — 将多源外部数据统一为标准格式。

对应 spec 01 §2 / §4、架构 §4.3 数据标准化流程。
对应 plan 0103 全部工作项：
  0103.1 字段映射与代码映射
  0103.2 单位与币种统一
  0103.3 时间标准化
  0103.4 标准数据事件发布

标准化流程（架构 §4.3）：
  外部数据 → 字段映射 → 代码映射 → 单位和币种统一 → 时间标准化 → 质量校验 → 标准数据事件
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# 0103.1 代码映射
# ---------------------------------------------------------------------------


class Exchange(StrEnum):
    """A 股交易所。"""

    SH = "SH"
    SZ = "SZ"


def normalize_symbol(raw: str) -> str:
    """将各种格式代码统一为 ``000001.SZ`` / ``600000.SH`` 口径。

    支持输入格式：
    - ``000001`` / ``600000``（纯数字，按规则推断交易所）
    - ``000001.SZ`` / ``600000.SH``（已标准）
    - ``SZ000001`` / ``SH600000``（前缀格式）
    - ``000001.sz`` / ``600000.sh``（小写）
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
    """拆分标准 symbol 为 (code, exchange)。"""
    if "." not in symbol:
        raise ValueError(f"Invalid symbol format: {symbol}")
    code, exchange = symbol.split(".", 1)
    return code, exchange.upper()


# ---------------------------------------------------------------------------
# 0103.1 字段映射
# ---------------------------------------------------------------------------


class DataDomain(StrEnum):
    """数据域（架构 §4.1）。"""

    MARKET_BAR = "market_bar"
    FINANCIAL = "financial"
    SECURITY_META = "security_meta"
    INDEX_MEMBER = "index_member"
    ADJUSTMENT_FACTOR = "adjustment_factor"
    CORPORATE_ACTION = "corporate_action"


class FieldMapping(BaseModel):
    """单个字段的映射规则。"""

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


# ---------------------------------------------------------------------------
# 0103.2 单位与币种统一
# ---------------------------------------------------------------------------


class UnitConverter:
    """单位与币种统一。

    A 股数据默认人民币 CNY，金额单位统一为元，成交量统一为股。
    部分外部源返回万元或手，需通过 unit_factor 转换。
    """

    CURRENCY = "CNY"

    @staticmethod
    def convert_amount(value: float, source_unit: str = "yuan") -> float:
        """金额统一为元。"""
        if source_unit == "qian_yuan":
            return value * 1000.0
        if source_unit == "wan_yuan":
            return value * 10000.0
        if source_unit == "yi_yuan":
            return value * 100000000.0
        return value

    @staticmethod
    def convert_volume(value: float, source_unit: str = "gu") -> float:
        """成交量统一为股。"""
        if source_unit == "shou":
            return value * 100.0
        return value


# ---------------------------------------------------------------------------
# 0103.3 时间标准化
# ---------------------------------------------------------------------------


class TimeStandardizer:
    """时间标准化，产出五项时点字段（架构 §4.4）。"""

    @staticmethod
    def parse_date(value: Any) -> datetime | None:
        """解析多种日期格式为 datetime。"""
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
        """生成完整的时点字段集。"""
        now = datetime.now()
        return {
            "event_at": event_at or now,
            "published_at": published_at or event_at or now,
            "available_at": available_at or published_at or event_at or now,
            "fetched_at": fetched_at or now,
            "revised_at": revised_at,
        }


def market_bar_available_at(trade_date: datetime) -> datetime:
    """Daily A-share bars are only usable after the close of their trade date."""
    return datetime.combine(trade_date.date(), time(hour=15))


def next_market_open_after(value: datetime) -> datetime:
    """Conservative availability for announcements without an exact release time."""
    return datetime.combine((value + timedelta(days=1)).date(), time(hour=9, minute=30))


# ---------------------------------------------------------------------------
# 0103.4 标准数据事件
# ---------------------------------------------------------------------------


class StandardDataEvent(BaseModel):
    """标准数据事件（架构 §4.3 标准数据事件发布）。

    所有经标准化后的数据以事件形式发布，供存储层 ODS→DWD→PIT 消费。
    """

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
    """标准化器：将外部 Provider 返回的原始数据转为标准数据事件。

    流程：字段映射 → 代码映射 → 单位币种统一 → 时间标准化 → 标准数据事件。
    """

    def __init__(self, mapping_version: str = "v1") -> None:
        self._mapping_version = mapping_version

    def standardize_bars(
        self,
        raw_records: list[dict[str, Any]],
        source: str,
    ) -> list[StandardDataEvent]:
        """标准化行情数据。"""
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
        """标准化证券元数据。"""
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
        """标准化财务数据。"""
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
        """标准化指数成分数据。"""
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
