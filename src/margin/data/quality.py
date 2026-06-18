"""时点校验与数据质量检查模块。

对应 spec 01 §4 时点字段、§7 风险与降级。
对应架构 §4.4 时点字段、§4.5 防未来数据泄漏、§25 故障降级。
对应 plan 0104 全部工作项：
  0104.1 时点字段落库
  0104.2 防未来数据泄漏校验
  0104.3 数据质量检查
  0104.4 数据质量事件发布
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from margin.data.standardize import StandardDataEvent

# ---------------------------------------------------------------------------
# 0104.1 时点字段
# ---------------------------------------------------------------------------


PIT_FIELDS = ("event_at", "published_at", "available_at", "fetched_at", "revised_at")


class PITFieldError(ValueError):
    """时点字段缺失或非法。"""


def validate_pit_fields(record: dict[str, Any] | StandardDataEvent) -> None:
    """验证记录含全部必需时点字段且类型正确。

    Args:
        record: 含时点字段的字典或 StandardDataEvent。

    Raises:
        PITFieldError: 缺失字段或类型错误。
    """
    if isinstance(record, StandardDataEvent):
        for field_name in ("event_at", "published_at", "available_at", "fetched_at"):
            value = getattr(record, field_name)
            if not isinstance(value, datetime):
                raise PITFieldError(f"Field '{field_name}' must be datetime, got {type(value)}")
        if record.revised_at is not None and not isinstance(record.revised_at, datetime):
            raise PITFieldError("Field 'revised_at' must be datetime or None")
        return

    for field_name in ("event_at", "published_at", "available_at", "fetched_at"):
        if field_name not in record:
            raise PITFieldError(f"Missing required PIT field: {field_name}")
        if not isinstance(record[field_name], datetime):
            raise PITFieldError(
                f"Field '{field_name}' must be datetime, got {type(record[field_name])}"
            )

    revised = record.get("revised_at")
    if revised is not None and not isinstance(revised, datetime):
        raise PITFieldError("Field 'revised_at' must be datetime or None")


# ---------------------------------------------------------------------------
# 0104.2 防未来数据泄漏
# ---------------------------------------------------------------------------


class LookaheadError(ValueError):
    """未来数据泄漏：available_at 晚于 decision_at。"""


def check_no_lookahead(
    record: dict[str, Any] | StandardDataEvent,
    decision_at: datetime,
) -> bool:
    """校验 ``available_at <= decision_at``，防止未来数据泄漏（架构 §4.5）。

    Args:
        record: 含 available_at 的记录。
        decision_at: 决策时点。

    Returns:
        True 如果通过校验。

    Raises:
        LookaheadError: available_at 晚于 decision_at。
    """
    if isinstance(record, StandardDataEvent):
        available_at = record.available_at
    else:
        available_at = record.get("available_at")

    if available_at is None:
        raise LookaheadError("available_at is None, cannot check lookahead")

    if available_at > decision_at:
        raise LookaheadError(
            f"Lookahead detected: available_at={available_at} > decision_at={decision_at}"
        )
    return True


def filter_by_decision_at(
    records: list[StandardDataEvent],
    decision_at: datetime,
) -> tuple[list[StandardDataEvent], list[StandardDataEvent]]:
    """按 decision_at 过滤记录，返回 (通过, 拒绝) 两列表。

    被拒绝的记录记入泄漏风险日志。
    """
    passed: list[StandardDataEvent] = []
    rejected: list[StandardDataEvent] = []
    for record in records:
        if record.available_at <= decision_at:
            passed.append(record)
        else:
            rejected.append(record)
    return passed, rejected


# ---------------------------------------------------------------------------
# 0104.3 数据质量检查
# ---------------------------------------------------------------------------


class QualityIssueType(StrEnum):
    """数据质量问题类型。"""

    MISSING_FIELD = "missing_field"
    MISSING_VALUE = "missing_value"
    OUTLIER = "outlier"
    REVISION = "revision"
    STALE_DATA = "stale_data"
    DUPLICATE = "duplicate"
    LOOKAHEAD = "lookahead"


class QualityIssue(BaseModel):
    """单条数据质量问题。"""

    issue_type: QualityIssueType
    symbol: str | None = None
    field_name: str | None = None
    message: str
    severity: str = "warning"

    model_config = {"frozen": True}


class QualityReport(BaseModel):
    """数据质量检查报告。"""

    checked_at: datetime = Field(default_factory=lambda: datetime.now())
    total_records: int = 0
    issues: list[QualityIssue] = Field(default_factory=list)
    passed: bool = True

    @property
    def issue_count(self) -> int:
        return len(self.issues)

    @property
    def critical_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "critical")


class DataQualityChecker:
    """数据质量检查器。

    检查项：
    - 必填字段缺失（MISSING_FIELD / MISSING_VALUE）
    - 异常值（OUTLIER）：价格/量为负或为零
    - 数据修订追踪（REVISION）：revised_at 存在时标记
    - 数据陈旧（STALE_DATA）：fetched_at 远晚于 available_at
    """

    def __init__(
        self,
        required_fields: dict[str, list[str]] | None = None,
        stale_threshold_hours: float = 72.0,
    ) -> None:
        self._required_fields = required_fields or {
            "market_bar": ["open", "close", "high", "low", "volume"],
            "financial": ["roe"],
            "security_meta": ["name"],
            "index_member": ["index_code"],
        }
        self._stale_threshold_hours = stale_threshold_hours

    def check(self, records: list[StandardDataEvent]) -> QualityReport:
        """对一批记录执行质量检查。"""
        issues: list[QualityIssue] = []

        for record in records:
            domain_str = record.domain.value
            required = self._required_fields.get(domain_str, [])

            for field_name in required:
                value = record.data.get(field_name)
                if value is None:
                    issues.append(
                        QualityIssue(
                            issue_type=QualityIssueType.MISSING_VALUE,
                            symbol=record.symbol,
                            field_name=field_name,
                            message=f"Missing value for '{field_name}' in {domain_str}",
                        )
                    )

            if record.revised_at is not None:
                issues.append(
                    QualityIssue(
                        issue_type=QualityIssueType.REVISION,
                        symbol=record.symbol,
                        message=f"Data revised at {record.revised_at}",
                        severity="info",
                    )
                )

            if domain_str == "market_bar":
                for price_field in ("open", "close", "high", "low"):
                    val = record.data.get(price_field, 0)
                    if val is not None and val <= 0:
                        issues.append(
                            QualityIssue(
                                issue_type=QualityIssueType.OUTLIER,
                                symbol=record.symbol,
                                field_name=price_field,
                                message=f"{price_field}={val} is non-positive",
                                severity="critical",
                            )
                        )
                vol = record.data.get("volume", 0)
                if vol is not None and vol < 0:
                    issues.append(
                        QualityIssue(
                            issue_type=QualityIssueType.OUTLIER,
                            symbol=record.symbol,
                            field_name="volume",
                            message=f"volume={vol} is negative",
                            severity="critical",
                        )
                    )

            delay_hours = (record.fetched_at - record.available_at).total_seconds() / 3600
            if delay_hours > self._stale_threshold_hours:
                issues.append(
                    QualityIssue(
                        issue_type=QualityIssueType.STALE_DATA,
                        symbol=record.symbol,
                        message=f"Data stale: fetched {delay_hours:.1f}h after available",
                        severity="warning",
                    )
                )

        passed = all(i.severity != "critical" for i in issues)
        return QualityReport(
            total_records=len(records),
            issues=issues,
            passed=passed,
        )


# ---------------------------------------------------------------------------
# 0104.4 数据质量事件
# ---------------------------------------------------------------------------


class QualityEventSeverity(StrEnum):
    """质量事件严重等级。"""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class DataQualityEvent(BaseModel):
    """数据质量事件 — 异常时向下游发送，触发停止高置信研究信号输出。

    对应架构 §25：核心数据冲突 → 停止发布高置信研究信号。
    对应产品 §15 条目 8：数据异常时停止高置信研究信号输出。
    """

    event_id: str
    severity: QualityEventSeverity
    source: str
    domain: str
    message: str
    affected_symbols: list[str] = Field(default_factory=list)
    issue_count: int = 0
    emitted_at: datetime = Field(default_factory=lambda: datetime.now())

    model_config = {"frozen": True}

    @property
    def should_suppress_research(self) -> bool:
        """critical 级别事件应停止高置信研究信号输出。"""
        return self.severity == QualityEventSeverity.CRITICAL


class QualityEventEmitter:
    """数据质量事件发射器。

    根据质量报告生成事件，critical 级别触发研究信号抑制。
    """

    def __init__(self) -> None:
        self._events: list[DataQualityEvent] = []
        self._counter = 0

    def emit_from_report(
        self,
        report: QualityReport,
        source: str,
        domain: str,
    ) -> DataQualityEvent | None:
        """根据质量报告生成事件，无问题时返回 None。"""
        if report.issue_count == 0:
            return None

        critical = report.critical_count
        if critical > 0:
            severity = QualityEventSeverity.CRITICAL
        elif any(i.severity == "warning" for i in report.issues):
            severity = QualityEventSeverity.WARNING
        else:
            severity = QualityEventSeverity.INFO

        self._counter += 1
        affected = sorted({
            i.symbol for i in report.issues if i.symbol is not None
        })

        event = DataQualityEvent(
            event_id=f"qe_{self._counter:06d}",
            severity=severity,
            source=source,
            domain=domain,
            message=(
                f"{report.issue_count} issues ({critical} critical)"
                f" in {report.total_records} records"
            ),
            affected_symbols=affected,
            issue_count=report.issue_count,
        )
        self._events.append(event)
        return event

    def emit_custom(
        self,
        severity: QualityEventSeverity,
        source: str,
        domain: str,
        message: str,
        affected_symbols: list[str] | None = None,
    ) -> DataQualityEvent:
        """发射自定义质量事件。"""
        self._counter += 1
        event = DataQualityEvent(
            event_id=f"qe_{self._counter:06d}",
            severity=severity,
            source=source,
            domain=domain,
            message=message,
            affected_symbols=affected_symbols or [],
        )
        self._events.append(event)
        return event

    @property
    def events(self) -> list[DataQualityEvent]:
        return list(self._events)

    @property
    def has_critical(self) -> bool:
        """是否存在 critical 级别事件（应停止高置信研究信号）。"""
        return any(e.should_suppress_research for e in self._events)
