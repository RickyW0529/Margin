"""Tests for point-in-time (PIT) validation and data quality checks.

Acceptance: 0104.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from margin.data.quality import (
    DataQualityChecker,
    LookaheadError,
    PITFieldError,
    QualityEventEmitter,
    QualityEventSeverity,
    check_no_lookahead,
    filter_by_decision_at,
    validate_pit_fields,
)
from margin.data.standardize import DataDomain, StandardDataEvent


def _make_bar(
    symbol: str = "000001.SZ",
    available_at: datetime | None = None,
    fetched_at: datetime | None = None,
    close: float = 11.0,
    revised_at: datetime | None = None,
) -> StandardDataEvent:
    """Create a ``StandardDataEvent`` market-bar fixture for testing.

    Args:
        symbol: str: .
        available_at: datetime | None: .
        fetched_at: datetime | None: .
        close: float: .
        revised_at: datetime | None: .

    Returns:
        StandardDataEvent: .
    """
    available = available_at or datetime(2026, 6, 17)
    return StandardDataEvent(
        domain=DataDomain.MARKET_BAR,
        symbol=symbol,
        data={"open": 10.5, "close": close, "high": 11.2, "low": 10.3, "volume": 1000.0},
        event_at=available,
        published_at=available,
        available_at=available,
        fetched_at=fetched_at or datetime(2026, 6, 18),
        revised_at=revised_at,
        source="akshare",
    )


class TestValidatePITFields:
    """Unit tests for ``validate_pit_fields`` ensuring required PIT fields are present and
    typed..
    """

    def test_valid_event(self):
        """A complete ``StandardDataEvent`` passes validation without raising.

        Returns:
            Any: .
        """
        event = _make_bar()
        validate_pit_fields(event)

    def test_valid_dict(self):
        """A dictionary containing all required PIT datetime fields passes validation.

        Returns:
            Any: .
        """
        record = {
            "event_at": datetime(2026, 6, 17),
            "published_at": datetime(2026, 6, 17),
            "available_at": datetime(2026, 6, 17),
            "fetched_at": datetime(2026, 6, 18),
            "revised_at": None,
        }
        validate_pit_fields(record)

    def test_missing_field_raises(self):
        """Validation raises ``PITFieldError`` when a required PIT field is missing.

        Returns:
            Any: .
        """
        record = {
            "event_at": datetime(2026, 6, 17),
            "published_at": datetime(2026, 6, 17),
        }
        with pytest.raises(PITFieldError, match="available_at"):
            validate_pit_fields(record)

    def test_wrong_type_raises(self):
        """Validation raises ``PITFieldError`` when a PIT field has the wrong type.

        Returns:
            Any: .
        """
        record = {
            "event_at": "2026-06-17",
            "published_at": datetime(2026, 6, 17),
            "available_at": datetime(2026, 6, 17),
            "fetched_at": datetime(2026, 6, 18),
        }
        with pytest.raises(PITFieldError, match="must be datetime"):
            validate_pit_fields(record)

    def test_revised_at_none_ok(self):
        """A ``None`` ``revised_at`` value is accepted.

        Returns:
            Any: .
        """
        event = _make_bar(revised_at=None)
        validate_pit_fields(event)

    def test_revised_at_datetime_ok(self):
        """A datetime ``revised_at`` value is accepted.

        Returns:
            Any: .
        """
        event = _make_bar(revised_at=datetime(2026, 6, 19))
        validate_pit_fields(event)


class TestCheckNoLookahead:
    """Unit tests for ``check_no_lookahead`` preventing future data leakage.."""

    def test_passes_when_available_before_decision(self):
        """Returns ``True`` when ``available_at`` is earlier than ``decision_at``.

        Returns:
            Any: .
        """
        event = _make_bar(available_at=datetime(2026, 6, 17))
        assert check_no_lookahead(event, datetime(2026, 6, 18)) is True

    def test_passes_when_equal(self):
        """Returns ``True`` when ``available_at`` equals ``decision_at``.

        Returns:
            Any: .
        """
        event = _make_bar(available_at=datetime(2026, 6, 17))
        assert check_no_lookahead(event, datetime(2026, 6, 17)) is True

    def test_raises_when_available_after_decision(self):
        """Raises ``LookaheadError`` when ``available_at`` is after ``decision_at``.

        Returns:
            Any: .
        """
        event = _make_bar(available_at=datetime(2026, 6, 18))
        with pytest.raises(LookaheadError, match="Lookahead detected"):
            check_no_lookahead(event, datetime(2026, 6, 17))

    def test_dict_record(self):
        """Detects lookahead for a plain dictionary record.

        Returns:
            Any: .
        """
        record = {"available_at": datetime(2026, 6, 18)}
        with pytest.raises(LookaheadError):
            check_no_lookahead(record, datetime(2026, 6, 17))

    def test_none_available_at_raises(self):
        """Raises ``LookaheadError`` when ``available_at`` is ``None``.

        Returns:
            Any: .
        """
        record = {"available_at": None}
        with pytest.raises(LookaheadError, match="None"):
            check_no_lookahead(record, datetime(2026, 6, 17))


class TestFilterByDecisionAt:
    """Unit tests for ``filter_by_decision_at`` splitting records by availability.."""

    def test_split_passed_rejected(self):
        """Splits records into passed and rejected groups based on ``decision_at``.

        Returns:
            Any: .
        """
        records = [
            _make_bar(available_at=datetime(2026, 6, 15)),
            _make_bar(available_at=datetime(2026, 6, 16)),
            _make_bar(available_at=datetime(2026, 6, 18)),
        ]
        decision_at = datetime(2026, 6, 17)
        passed, rejected = filter_by_decision_at(records, decision_at)
        assert len(passed) == 2
        assert len(rejected) == 1

    def test_all_pass(self):
        """Returns all records as passed when every ``available_at`` is before ``decision_at``.

        Returns:
            Any: .
        """
        records = [_make_bar(available_at=datetime(2026, 6, 15))]
        passed, rejected = filter_by_decision_at(records, datetime(2026, 6, 17))
        assert len(passed) == 1
        assert len(rejected) == 0

    def test_all_rejected(self):
        """Returns all records as rejected when every ``available_at`` is after ``decision_at``.

        Returns:
            Any: .
        """
        records = [_make_bar(available_at=datetime(2026, 6, 20))]
        passed, rejected = filter_by_decision_at(records, datetime(2026, 6, 17))
        assert len(passed) == 0
        assert len(rejected) == 1


class TestDataQualityChecker:
    """Unit tests for ``DataQualityChecker`` (missing values, outliers, revisions, stale
    data)..
    """

    def test_clean_records_pass(self):
        """Clean records produce a passing report with no issues.

        Returns:
            Any: .
        """
        records = [_make_bar()]
        checker = DataQualityChecker()
        report = checker.check(records)
        assert report.passed is True
        assert report.issue_count == 0

    def test_missing_value_detected(self):
        """Detects a missing ``volume`` field and reports it as a missing-value issue.

        Returns:
            Any: .
        """
        event = StandardDataEvent(
            domain=DataDomain.MARKET_BAR,
            symbol="000001.SZ",
            data={"open": 10.0, "close": 11.0, "high": 11.0, "low": 10.0},
            event_at=datetime(2026, 6, 17),
            published_at=datetime(2026, 6, 17),
            available_at=datetime(2026, 6, 17),
            fetched_at=datetime(2026, 6, 18),
            source="akshare",
        )
        checker = DataQualityChecker()
        report = checker.check([event])
        assert any(
            i.issue_type.value == "missing_value" and i.field_name == "volume"
            for i in report.issues
        )

    def test_outlier_negative_price_critical(self):
        """A negative closing price is flagged as a critical outlier issue.

        Returns:
            Any: .
        """
        event = _make_bar(close=-5.0)
        checker = DataQualityChecker()
        report = checker.check([event])
        assert not report.passed
        assert report.critical_count > 0
        assert any(i.issue_type.value == "outlier" for i in report.issues)

    def test_revision_tracked(self):
        """A non-null ``revised_at`` timestamp is reported as a revision issue.

        Returns:
            Any: .
        """
        event = _make_bar(revised_at=datetime(2026, 6, 19))
        checker = DataQualityChecker()
        report = checker.check([event])
        assert any(i.issue_type.value == "revision" for i in report.issues)

    def test_stale_data_detected(self):
        """Data older than the configured stale threshold is flagged as stale.

        Returns:
            Any: .
        """
        event = _make_bar(
            available_at=datetime(2026, 6, 1),
            fetched_at=datetime(2026, 6, 18),
        )
        checker = DataQualityChecker(stale_threshold_hours=72.0)
        report = checker.check([event])
        assert any(i.issue_type.value == "stale_data" for i in report.issues)

    def test_no_stale_within_threshold(self):
        """Fresh data within the stale threshold is not flagged.

        Returns:
            Any: .
        """
        event = _make_bar(
            available_at=datetime(2026, 6, 17),
            fetched_at=datetime(2026, 6, 18),
        )
        checker = DataQualityChecker(stale_threshold_hours=72.0)
        report = checker.check([event])
        assert not any(i.issue_type.value == "stale_data" for i in report.issues)

    def test_empty_records(self):
        """An empty input produces a passing report with zero records.

        Returns:
            Any: .
        """
        checker = DataQualityChecker()
        report = checker.check([])
        assert report.passed is True
        assert report.total_records == 0


class TestQualityEventEmitter:
    """Unit tests for ``QualityEventEmitter`` converting quality reports into domain events.."""

    def test_no_issues_returns_none(self):
        """An empty issue list results in no event being emitted.

        Returns:
            Any: .
        """
        from margin.data.quality import QualityReport

        emitter = QualityEventEmitter()
        report = QualityReport(total_records=5, issues=[], passed=True)
        event = emitter.emit_from_report(report, source="akshare", domain="market_bar")
        assert event is None

    def test_warning_event(self):
        """A warning issue emits a warning event that does not suppress research.

        Returns:
            Any: .
        """
        from margin.data.quality import QualityIssue, QualityIssueType, QualityReport

        emitter = QualityEventEmitter()
        report = QualityReport(
            total_records=10,
            issues=[
                QualityIssue(
                    issue_type=QualityIssueType.STALE_DATA,
                    symbol="000001.SZ",
                    message="stale",
                    severity="warning",
                ),
            ],
            passed=True,
        )
        event = emitter.emit_from_report(report, source="akshare", domain="market_bar")
        assert event is not None
        assert event.severity == QualityEventSeverity.WARNING
        assert event.should_suppress_research is False

    def test_critical_event_suppresses_research(self):
        """A critical issue emits a critical event that suppresses downstream research.

        Returns:
            Any: .
        """
        from margin.data.quality import QualityIssue, QualityIssueType, QualityReport

        emitter = QualityEventEmitter()
        report = QualityReport(
            total_records=10,
            issues=[
                QualityIssue(
                    issue_type=QualityIssueType.OUTLIER,
                    symbol="000001.SZ",
                    message="negative price",
                    severity="critical",
                ),
            ],
            passed=False,
        )
        event = emitter.emit_from_report(report, source="akshare", domain="market_bar")
        assert event is not None
        assert event.severity == QualityEventSeverity.CRITICAL
        assert event.should_suppress_research is True

    def test_has_critical_flag(self):
        """The emitter records that a critical event was emitted.

        Returns:
            Any: .
        """
        emitter = QualityEventEmitter()
        emitter.emit_custom(QualityEventSeverity.CRITICAL, "akshare", "market_bar", "data conflict")
        assert emitter.has_critical is True

    def test_no_critical_flag(self):
        """The emitter does not set the critical flag for warning events.

        Returns:
            Any: .
        """
        emitter = QualityEventEmitter()
        emitter.emit_custom(QualityEventSeverity.WARNING, "akshare", "market_bar", "stale")
        assert emitter.has_critical is False

    def test_event_id_unique(self):
        """Each emitted event receives a unique ``event_id``.

        Returns:
            Any: .
        """
        emitter = QualityEventEmitter()
        e1 = emitter.emit_custom(QualityEventSeverity.INFO, "s", "d", "m1")
        e2 = emitter.emit_custom(QualityEventSeverity.INFO, "s", "d", "m2")
        assert e1.event_id != e2.event_id

    def test_affected_symbols_collected(self):
        """Affected symbols from all report issues are aggregated on the emitted event.

        Returns:
            Any: .
        """
        from margin.data.quality import QualityIssue, QualityIssueType, QualityReport

        emitter = QualityEventEmitter()
        report = QualityReport(
            total_records=5,
            issues=[
                QualityIssue(
                    issue_type=QualityIssueType.OUTLIER,
                    symbol="000001.SZ",
                    message="m",
                    severity="critical",
                ),
                QualityIssue(
                    issue_type=QualityIssueType.OUTLIER,
                    symbol="600000.SH",
                    message="m",
                    severity="critical",
                ),
            ],
            passed=False,
        )
        event = emitter.emit_from_report(report, source="akshare", domain="market_bar")
        assert "000001.SZ" in event.affected_symbols
        assert "600000.SH" in event.affected_symbols

    def test_event_frozen(self):
        """Emitted events are immutable and raise an exception when modified.

        Returns:
            Any: .
        """
        emitter = QualityEventEmitter()
        event = emitter.emit_custom(QualityEventSeverity.INFO, "s", "d", "m")
        with pytest.raises(Exception):
            event.message = "changed"


class TestEndToEnd:
    """End-to-end tests for the pipeline: standardize -> PIT validate -> quality check ->
    emit..
    """

    def test_full_pipeline_suppresses_on_critical(self):
        """Critical quality issues propagate through the pipeline and suppress research.

        Returns:
            Any: .
        """
        from margin.data.standardize import Standardizer

        std = Standardizer()
        checker = DataQualityChecker()
        emitter = QualityEventEmitter()

        raw = [
            {
                "symbol": "000001",
                "date": datetime(2026, 6, 17),
                "open": 10.0,
                "close": -5.0,
                "high": 11.0,
                "low": 10.0,
                "volume": 1000.0,
                "fetched_at": datetime(2026, 6, 18),
            },
        ]
        events = std.standardize_bars(raw, source="akshare")

        for e in events:
            validate_pit_fields(e)

        decision_at = datetime(2026, 6, 18)
        for e in events:
            check_no_lookahead(e, decision_at)

        report = checker.check(events)
        assert not report.passed

        event = emitter.emit_from_report(report, source="akshare", domain="market_bar")
        assert event is not None
        assert event.should_suppress_research is True
        assert emitter.has_critical is True

    def test_future_data_rejected_before_quality_check(self):
        """Future data is filtered out before it reaches the quality checker.

        Returns:
            Any: .
        """
        from margin.data.standardize import Standardizer

        std = Standardizer()
        raw = [
            {
                "symbol": "000001",
                "date": datetime(2026, 6, 20),
                "open": 10.0,
                "close": 11.0,
                "high": 11.0,
                "low": 10.0,
                "volume": 1000.0,
                "fetched_at": datetime(2026, 6, 18),
            },
        ]
        events = std.standardize_bars(raw, source="akshare")
        decision_at = datetime(2026, 6, 18)
        passed, rejected = filter_by_decision_at(events, decision_at)
        assert len(rejected) == 1
        assert len(passed) == 0
