"""MemoryQuantRepository latest_result_for_security unit tests."""

from __future__ import annotations

from datetime import UTC, datetime

from margin.valuation_discovery.models import (
    DataStatus,
    QuantResult,
    ResearchGuardrail,
    ScreeningStatus,
)
from margin.valuation_discovery.quant.repository import MemoryQuantRepository


def _make_result(
    *,
    security_id: str,
    final_score: float,
    created_at: datetime,
    quant_run_id: str = "qr_001",
) -> QuantResult:
    """Build a minimal quant result.

    Args:
        security_id: str: .
        final_score: float: .
        created_at: datetime: .
        quant_run_id: str: .

    Returns:
        QuantResult: .
    """
    return QuantResult(
        result_id=f"qres_{security_id}_{int(created_at.timestamp())}_{quant_run_id}",
        quant_run_id=quant_run_id,
        security_id=security_id,
        final_score=final_score,
        quality_score=70.0,
        value_score=80.0,
        growth_score=60.0,
        momentum_score=65.0,
        risk_score=55.0,
        rank_overall=1,
        rank_in_industry=1,
        screening_status=ScreeningStatus.PASS,
        data_status=DataStatus.OK,
        risk_flags=(),
        review_required=False,
        review_reasons=(),
        research_guardrail=ResearchGuardrail.RESEARCH_ALLOWED,
        reason_summary="",
        factor_details={},
        created_at=created_at,
    )


def test_latest_result_for_security_returns_none_when_empty() -> None:
    """Repository returns None when no results exist.

    Returns:
        None: .
    """
    repo = MemoryQuantRepository()
    assert repo.latest_result_for_security("sec_001") is None


def test_latest_result_for_security_returns_most_recent() -> None:
    """Repository returns the most recent result for a security.

    Returns:
        None: .
    """
    repo = MemoryQuantRepository()
    earlier = _make_result(
        security_id="sec_001",
        final_score=70.0,
        created_at=datetime(2026, 6, 24, 8, 0, tzinfo=UTC),
    )
    later = _make_result(
        security_id="sec_001",
        final_score=85.0,
        created_at=datetime(2026, 6, 25, 8, 0, tzinfo=UTC),
    )
    repo.add_results("qr_001", (earlier, later))

    result = repo.latest_result_for_security("sec_001")
    assert result is not None
    assert result.final_score == 85.0


def test_latest_result_for_security_isolates_by_security() -> None:
    """Repository only returns results for the requested security.

    Returns:
        None: .
    """
    repo = MemoryQuantRepository()
    sec_a = _make_result(
        security_id="sec_a",
        final_score=70.0,
        created_at=datetime(2026, 6, 24, 8, 0, tzinfo=UTC),
    )
    sec_b = _make_result(
        security_id="sec_b",
        final_score=90.0,
        created_at=datetime(2026, 6, 25, 8, 0, tzinfo=UTC),
    )
    repo.add_results("qr_001", (sec_a, sec_b))

    result = repo.latest_result_for_security("sec_a")
    assert result is not None
    assert result.security_id == "sec_a"
    assert result.final_score == 70.0


def test_latest_result_for_security_across_multiple_runs() -> None:
    """Repository finds the latest result across multiple runs.

    Returns:
        None: .
    """
    repo = MemoryQuantRepository()
    run1 = _make_result(
        security_id="sec_001",
        final_score=60.0,
        created_at=datetime(2026, 6, 23, 8, 0, tzinfo=UTC),
    )
    run2 = _make_result(
        security_id="sec_001",
        final_score=75.0,
        created_at=datetime(2026, 6, 26, 8, 0, tzinfo=UTC),
        quant_run_id="qr_002",
    )
    repo.add_results("qr_001", (run1,))
    repo.add_results("qr_002", (run2,))

    result = repo.latest_result_for_security("sec_001")
    assert result is not None
    assert result.final_score == 75.0
