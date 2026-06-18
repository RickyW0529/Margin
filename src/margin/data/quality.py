"""Point-in-time validation and data quality checking module.

Corresponds to specs 01 §4 point-in-time fields and §7 risks and degradation.
Corresponds to architecture §4.4 point-in-time fields, §4.5 anti-future data
leakage prevention, and §25 fault degradation.
Corresponds to plans 0104 work items:
  0104.1 point-in-time field persistence
  0104.2 anti-future data leakage validation
  0104.3 data quality checks
  0104.4 data quality event publishing
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from margin.data.standardize import StandardDataEvent

# ---------------------------------------------------------------------------
# 0104.1 point-in-time fields
# ---------------------------------------------------------------------------


PIT_FIELDS = ("event_at", "published_at", "available_at", "fetched_at", "revised_at")


class PITFieldError(ValueError):
    """Raised when a required point-in-time field is missing or has an invalid type."""


def validate_pit_fields(record: dict[str, Any] | StandardDataEvent) -> None:
    """Validate that a record contains all required point-in-time fields with correct types.

    The required fields are ``event_at``, ``published_at``, ``available_at``,
    and ``fetched_at``. ``revised_at`` is optional and may be ``None``.

    Args:
        record: A dictionary or ``StandardDataEvent`` containing point-in-time fields.

    Raises:
        PITFieldError: If a required field is missing or has an incorrect type.
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
# 0104.2 anti-future data leakage prevention
# ---------------------------------------------------------------------------


class LookaheadError(ValueError):
    """Raised when ``available_at`` is later than ``decision_at``.

    This indicates future data leakage: the record was not yet available at the
    simulated decision time.
    """


def check_no_lookahead(
    record: dict[str, Any] | StandardDataEvent,
    decision_at: datetime,
) -> bool:
    """Verify ``available_at <= decision_at`` to prevent future data leakage.

    See architecture §4.5 for the anti-lookahead design rationale.

    Args:
        record: A record containing ``available_at``.
        decision_at: The point in time at which a decision would be made.

    Returns:
        ``True`` if the check passes.

    Raises:
        LookaheadError: If ``available_at`` is ``None`` or later than ``decision_at``.
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
    """Filter records based on ``decision_at``.

    Records with ``available_at`` later than ``decision_at`` are considered
    future data leakage and are returned as rejected.

    Args:
        records: List of records to filter.
        decision_at: The decision point used for filtering.

    Returns:
        A tuple of ``(passed_records, rejected_records)``.
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
# 0104.3 data quality checks
# ---------------------------------------------------------------------------


class QualityIssueType(StrEnum):
    """Enumeration of data quality issue types."""

    MISSING_FIELD = "missing_field"
    MISSING_VALUE = "missing_value"
    OUTLIER = "outlier"
    REVISION = "revision"
    STALE_DATA = "stale_data"
    DUPLICATE = "duplicate"
    LOOKAHEAD = "lookahead"


class QualityIssue(BaseModel):
    """A single data quality issue.

    Attributes:
        issue_type: The type of quality issue.
        symbol: The affected symbol, if any.
        field_name: The affected field name, if any.
        message: A human-readable description of the issue.
        severity: Issue severity; one of ``info``, ``warning``, or ``critical``.
    """

    issue_type: QualityIssueType
    symbol: str | None = None
    field_name: str | None = None
    message: str
    severity: str = "warning"

    model_config = {"frozen": True}


class QualityReport(BaseModel):
    """Report summarizing the result of a data quality check.

    Attributes:
        checked_at: Timestamp when the report was generated.
        total_records: Number of records that were inspected.
        issues: List of detected quality issues.
        passed: Whether the check passed; ``False`` if any critical issue exists.
    """

    checked_at: datetime = Field(default_factory=lambda: datetime.now())
    total_records: int = 0
    issues: list[QualityIssue] = Field(default_factory=list)
    passed: bool = True

    @property
    def issue_count(self) -> int:
        """Return the total number of issues in the report."""
        return len(self.issues)

    @property
    def critical_count(self) -> int:
        """Return the number of critical issues in the report."""
        return sum(1 for i in self.issues if i.severity == "critical")


class DataQualityChecker:
    """Inspects ``StandardDataEvent`` records and produces a ``QualityReport``.

    Checks performed include:

    - Required field/value presence (``MISSING_FIELD`` / ``MISSING_VALUE``).
    - Outlier detection (``OUTLIER``): non-positive prices or negative volume.
    - Revision tracking (``REVISION``): flagged when ``revised_at`` is set.
    - Staleness detection (``STALE_DATA``): ``fetched_at`` is much later than
      ``available_at``.

    Attributes:
        _required_fields: Mapping from domain name to required field names.
        _stale_threshold_hours: Threshold for stale data detection in hours.
    """

    def __init__(
        self,
        required_fields: dict[str, list[str]] | None = None,
        stale_threshold_hours: float = 72.0,
    ) -> None:
        """Initialize the checker with domain-specific required fields.

        Args:
            required_fields: Optional mapping of domain names to required field
                name lists. Defaults are used when not provided.
            stale_threshold_hours: Hours after which a record is considered stale.
        """
        self._required_fields = required_fields or {
            "market_bar": ["open", "close", "high", "low", "volume"],
            "financial": ["roe"],
            "security_meta": ["name"],
            "index_member": ["index_code"],
        }
        self._stale_threshold_hours = stale_threshold_hours

    def check(self, records: list[StandardDataEvent]) -> QualityReport:
        """Run quality checks on a batch of records.

        Args:
            records: Records to inspect.

        Returns:
            A ``QualityReport`` containing all detected issues.
        """
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
# 0104.4 data quality events
# ---------------------------------------------------------------------------


class QualityEventSeverity(StrEnum):
    """Severity levels for data quality events."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class DataQualityEvent(BaseModel):
    """Data quality event emitted downstream when anomalies are detected.

    Critical events can be used to suppress high-confidence research signal
    output, as described in architecture §25 and product §15 item 8.

    Attributes:
        event_id: Unique identifier for the event.
        severity: Event severity level.
        source: Source component that emitted the event.
        domain: Data domain affected by the event.
        message: Human-readable event description.
        affected_symbols: Symbols impacted by the event.
        issue_count: Number of underlying quality issues.
        emitted_at: Timestamp when the event was emitted.
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
        """Return whether this critical event should suppress research signals."""
        return self.severity == QualityEventSeverity.CRITICAL


class QualityEventEmitter:
    """Generates and tracks ``DataQualityEvent`` instances.

    Events are derived from ``QualityReport`` objects or created manually for
    custom notifications. Critical events may be consumed to suppress research
    signal output.

    Attributes:
        _events: Internal list of emitted events.
        _counter: Monotonically increasing event counter.
    """

    def __init__(self) -> None:
        """Initialize the emitter with an empty event history."""
        self._events: list[DataQualityEvent] = []
        self._counter = 0

    def emit_from_report(
        self,
        report: QualityReport,
        source: str,
        domain: str,
    ) -> DataQualityEvent | None:
        """Create a ``DataQualityEvent`` from a ``QualityReport``.

        Args:
            report: The quality report to convert.
            source: Source component name to record in the event.
            domain: Data domain name to record in the event.

        Returns:
            A new ``DataQualityEvent`` if the report contains issues, otherwise
            ``None``.
        """
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
        """Emit a custom data quality event.

        Args:
            severity: Severity level for the event.
            source: Source component name.
            domain: Data domain name.
            message: Human-readable event description.
            affected_symbols: Optional list of affected symbols.

        Returns:
            The newly emitted ``DataQualityEvent``.
        """
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
        """Return a copy of all emitted events."""
        return list(self._events)

    @property
    def has_critical(self) -> bool:
        """Return whether any emitted event is critical.

        Critical events should trigger suppression of high-confidence research
        signal output.
        """
        return any(e.should_suppress_research for e in self._events)
