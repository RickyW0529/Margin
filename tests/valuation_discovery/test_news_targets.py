"""News target selector and refresh policy tests."""

from __future__ import annotations

from margin.valuation_discovery.models import (
    DataStatus,
    QuantResult,
    ResearchGuardrail,
    ScreeningStatus,
)
from margin.valuation_discovery.news_targets import NewsTargetSelector
from margin.valuation_discovery.refresh_policy import RefreshPolicy


def test_selector_includes_all_pass_without_top_n_limit() -> None:
    """selector includes all pass without top n limit."""
    results = [
        _result_with_status(f"000{i:03d}.SZ", ScreeningStatus.PASS)
        for i in range(120)
    ]
    selector = NewsTargetSelector()

    targets = selector.select(
        scope_version_id="scope-1",
        quant_run_id="quant-1",
        results=results,
    )

    assert len(targets) == 120
    assert targets[0].scope_version_id == "scope-1"
    assert {target.security_id for target in targets} == {
        f"000{i:03d}.SZ" for i in range(120)
    }


def test_selector_includes_near_threshold_only_when_strategy_allows() -> None:
    """selector includes near threshold only when strategy allows."""
    near = _result_with_status(
        "000001.SZ",
        ScreeningStatus.NEAR_THRESHOLD,
        guardrail=ResearchGuardrail.LIMITED_RESEARCH,
    )

    allowed_targets = NewsTargetSelector(include_near_threshold=True).select(
        scope_version_id="scope-1",
        quant_run_id="quant-1",
        results=(near,),
    )
    blocked_targets = NewsTargetSelector(include_near_threshold=False).select(
        scope_version_id="scope-1",
        quant_run_id="quant-1",
        results=(near,),
    )

    assert [target.security_id for target in allowed_targets] == ["000001.SZ"]
    assert blocked_targets == ()


def test_selector_excludes_research_blocked_results() -> None:
    """selector excludes research blocked results."""
    blocked = _result_with_status(
        "000001.SZ",
        ScreeningStatus.PASS,
        guardrail=ResearchGuardrail.RESEARCH_BLOCKED,
    )

    targets = NewsTargetSelector().select(
        scope_version_id="scope-1",
        quant_run_id="quant-1",
        results=(blocked,),
    )

    assert targets == ()


def test_priority_increases_for_review_due_and_material_events() -> None:
    """priority increases for review due and material events."""
    normal = _result_with_status("000001.SZ", ScreeningStatus.PASS)
    urgent = _result_with_status(
        "000002.SZ",
        ScreeningStatus.PASS,
        review_required=True,
        factor_details={"material_filing": True, "thesis_invalidation_risk": True},
    )

    targets = NewsTargetSelector().select(
        scope_version_id="scope-1",
        quant_run_id="quant-1",
        results=(normal, urgent),
    )

    assert targets[0].security_id == "000002.SZ"
    assert targets[0].priority > targets[1].priority


def test_price_change_only_recalculates_discount_without_ai_event() -> None:
    """price change only recalculates discount without ai event."""
    event = RefreshPolicy().classify_price_move(
        security_id="000001.SZ",
        old_discount=0.20,
        new_discount=0.22,
        watch_band=(0.30, 0.35),
    )

    assert event.recalculate_discount is True
    assert event.create_ai_refresh is False
    assert event.create_news_target is False


def test_entering_watch_band_creates_news_target() -> None:
    """entering watch band creates news target."""
    event = RefreshPolicy().classify_price_move(
        security_id="000001.SZ",
        old_discount=0.20,
        new_discount=0.31,
        watch_band=(0.30, 0.35),
    )

    assert event.recalculate_discount is True
    assert event.create_news_target is True


def test_refresh_policy_failure_semantics() -> None:
    """refresh policy failure semantics."""
    policy = RefreshPolicy()

    assert policy.classify_step_failure(step="run_quant").stop_downstream is True
    news_failure = policy.classify_step_failure(step="acquire_news")
    assert news_failure.defer_ai_review is True
    assert news_failure.stop_downstream is False


def _result_with_status(
    security_id: str,
    status: ScreeningStatus,
    *,
    guardrail: ResearchGuardrail = ResearchGuardrail.RESEARCH_ALLOWED,
    review_required: bool = False,
    factor_details: dict[str, object] | None = None,
) -> QuantResult:
    """result with status."""
    return QuantResult(
        quant_run_id="quant-1",
        security_id=security_id,
        final_score=80.0,
        screening_status=status,
        data_status=DataStatus.OK,
        review_required=review_required,
        research_guardrail=guardrail,
        factor_details=factor_details or {},
    )
