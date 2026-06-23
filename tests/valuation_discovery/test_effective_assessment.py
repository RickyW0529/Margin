"""Effective assessment pointer semantics tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from margin.valuation_discovery.assessments import EffectiveAssessmentService


def test_review_deferred_keeps_previous_effective_assessment() -> None:
    """review deferred keeps previous effective assessment."""
    service = EffectiveAssessmentService()

    pointer = service.apply_review_result(
        security_id="000001.SZ",
        scope_version_id="scope-v1",
        previous_effective_assessment_id="assess-old",
        current_review_outcome="review_deferred",
        new_assessment_id=None,
        stale_reason="news_target_incomplete",
    )

    assert pointer.effective_assessment_id == "assess-old"
    assert pointer.assessment_freshness == "stale"
    assert pointer.stale_reason == "news_target_incomplete"


def test_invalidate_creates_new_effective_assessment() -> None:
    """invalidate creates new effective assessment."""
    service = EffectiveAssessmentService()

    pointer = service.apply_review_result(
        security_id="000001.SZ",
        scope_version_id="scope-v1",
        previous_effective_assessment_id="assess-old",
        current_review_outcome="invalidate",
        new_assessment_id="assess-invalidated",
        stale_reason=None,
    )

    assert pointer.effective_assessment_id == "assess-invalidated"
    assert pointer.assessment_freshness == "current"
    assert pointer.previous_assessment_id == "assess-old"


def test_carry_forward_verified_keeps_previous_and_updates_checks_independently() -> None:
    """carry forward verified keeps previous and updates checks independently."""
    service = EffectiveAssessmentService()
    data_check_at = datetime(2026, 6, 22, 9, 30, tzinfo=UTC)
    news_check_at = datetime(2026, 6, 22, 10, 0, tzinfo=UTC)

    pointer = service.apply_review_result(
        security_id="000001.SZ",
        scope_version_id="scope-v1",
        previous_effective_assessment_id="assess-old",
        current_review_outcome="carry_forward_verified",
        new_assessment_id=None,
        stale_reason=None,
        last_successful_data_check_at=data_check_at,
        last_successful_news_check_at=news_check_at,
    )

    assert pointer.effective_assessment_id == "assess-old"
    assert pointer.assessment_freshness == "verified"
    assert pointer.last_successful_data_check_at == data_check_at
    assert pointer.last_successful_news_check_at == news_check_at


def test_update_outcome_requires_new_assessment_id() -> None:
    """update outcome requires new assessment id."""
    service = EffectiveAssessmentService()

    with pytest.raises(ValueError, match="new_assessment_id is required"):
        service.apply_review_result(
            security_id="000001.SZ",
            scope_version_id="scope-v1",
            previous_effective_assessment_id="assess-old",
            current_review_outcome="update_assessment",
            new_assessment_id=None,
            stale_reason=None,
        )


def test_first_abstention_cannot_create_an_effective_pointer() -> None:
    """Abstaining without a previous conclusion cannot invent one."""
    service = EffectiveAssessmentService()

    with pytest.raises(ValueError, match="without a previous assessment"):
        service.apply_review_result(
            security_id="000001.SZ",
            scope_version_id="scope-v1",
            previous_effective_assessment_id=None,
            current_review_outcome="abstain",
            new_assessment_id=None,
            stale_reason="insufficient_evidence",
            effective_from=datetime(2026, 6, 23, tzinfo=UTC),
        )
