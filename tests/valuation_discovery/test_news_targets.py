"""News target selector and refresh policy tests.

This module validates that the news target selector includes pass and
near-threshold results, excludes research-blocked results, assigns priority
correctly, and that the refresh policy classifies price moves and step
failures appropriately.
"""

from __future__ import annotations

from datetime import UTC, datetime

from margin.news.models import TargetTriggerType
from margin.valuation_discovery.models import (
    DataStatus,
    QuantResult,
    ResearchGuardrail,
    ScreeningStatus,
)
from margin.valuation_discovery.news_targets import (
    FilingCatalystSeed,
    NewsTargetSelector,
    SQLAlchemyFilingCatalystCandidateLoader,
)
from margin.valuation_discovery.refresh_policy import RefreshPolicy


def test_selector_includes_all_pass_without_top_n_limit() -> None:
    """Verify the selector includes all pass results without a top-N limit.

    Returns:
        None: .
    """
    results = [_result_with_status(f"000{i:03d}.SZ", ScreeningStatus.PASS) for i in range(120)]
    selector = NewsTargetSelector()

    targets = selector.select(
        scope_version_id="scope-1",
        quant_run_id="quant-1",
        results=results,
    )

    assert len(targets) == 120
    assert targets[0].scope_version_id == "scope-1"
    assert {target.security_id for target in targets} == {f"000{i:03d}.SZ" for i in range(120)}


def test_selector_includes_near_threshold_only_when_strategy_allows() -> None:
    """Verify near-threshold results are included only when the strategy allows.

    Returns:
        None: .
    """
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
    """Verify the selector excludes results with a research-blocked guardrail.

    Returns:
        None: .
    """
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
    """Verify priority increases for review-due and material event results.

    Returns:
        None: .
    """
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


def test_new_filing_can_select_quant_reject_as_independent_catalyst_target() -> None:
    """Indexed filings enter research without requiring an ML pass."""
    decision_at = datetime(2026, 7, 15, tzinfo=UTC)
    filing_loader = _FilingCandidateLoader(
        seeds=(
            _filing_seed("000001.SZ", decision_at),
            _filing_seed("000002.SZ", decision_at),
            _filing_seed("000003.SZ", decision_at),
            _filing_seed("999999.SZ", decision_at),
        )
    )
    selector = NewsTargetSelector(filing_candidate_loader=filing_loader)
    results = (
        _result_with_status("000001.SZ", ScreeningStatus.PASS),
        _result_with_status("000002.SZ", ScreeningStatus.REJECT),
        _result_with_status(
            "000003.SZ",
            ScreeningStatus.REJECT,
            guardrail=ResearchGuardrail.RESEARCH_BLOCKED,
        ),
    )

    targets = selector.select(
        scope_version_id="scope-1",
        quant_run_id="quant-1",
        results=results,
        decision_at=decision_at,
    )

    assert filing_loader.calls == [("scope-1", decision_at)]
    assert [target.security_id for target in targets] == ["000001.SZ", "000002.SZ"]
    assert all(target.trigger_type is TargetTriggerType.MATERIAL_FILING for target in targets)
    assert targets[1].filing_event_ids == ("filing-000002.SZ",)
    assert len({target.security_id for target in targets}) == len(targets)


def test_sql_filing_loader_groups_only_unconsumed_reporting_window_events() -> None:
    """The production loader retries unreviewed filings and suppresses reviewed ones."""
    decision_at = datetime(2026, 7, 15, tzinfo=UTC)
    session = _FilingLoaderSession(
        prior_payloads=[{"new_filing_document_ids": ["filing-consumed"]}],
        filing_rows=[
            ("000001.SZ", "filing-consumed", datetime(2026, 7, 2, tzinfo=UTC)),
            ("000001.SZ", "filing-new-1", datetime(2026, 7, 10, tzinfo=UTC)),
            ("000002.SZ", "filing-new-2", datetime(2026, 7, 12, tzinfo=UTC)),
        ],
    )
    loader = SQLAlchemyFilingCatalystCandidateLoader(lambda: session)  # type: ignore[arg-type]

    seeds = loader.load(scope_version_id="scope-1", decision_at=decision_at)

    assert [seed.security_id for seed in seeds] == ["000001.SZ", "000002.SZ"]
    assert seeds[0].filing_event_ids == ("filing-new-1",)
    assert seeds[1].latest_available_at == datetime(2026, 7, 12, tzinfo=UTC)


def test_price_change_only_recalculates_discount_without_ai_event() -> None:
    """Verify a price change only recalculates discount without triggering an AI event.

    Returns:
        None: .
    """
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
    """Verify entering the watch band creates a news target.

    Returns:
        None: .
    """
    event = RefreshPolicy().classify_price_move(
        security_id="000001.SZ",
        old_discount=0.20,
        new_discount=0.31,
        watch_band=(0.30, 0.35),
    )

    assert event.recalculate_discount is True
    assert event.create_news_target is True


def test_refresh_policy_failure_semantics() -> None:
    """Verify refresh policy classifies step failures with correct downstream semantics.

    Returns:
        None: .
    """
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
    """Build one deterministic QuantResult with the given screening status.

    Args:
        security_id: str: .
        status: ScreeningStatus: .
        guardrail: ResearchGuardrail: .
        review_required: bool: .
        factor_details: dict[str, object] | None: .

    Returns:
        QuantResult: .
    """
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


class _FilingCandidateLoader:
    """Deterministic filing seed boundary for selector tests."""

    def __init__(self, *, seeds: tuple[FilingCatalystSeed, ...]) -> None:
        self.seeds = seeds
        self.calls: list[tuple[str, datetime]] = []

    def load(
        self,
        *,
        scope_version_id: str,
        decision_at: datetime,
    ) -> tuple[FilingCatalystSeed, ...]:
        self.calls.append((scope_version_id, decision_at))
        return self.seeds


class _Rows:
    """Small SQLAlchemy-result stand-in for loader unit tests."""

    def __init__(self, values: list[object]) -> None:
        self._values = values

    def all(self) -> list[object]:
        return self._values


class _FilingLoaderSession:
    """Context-managed session returning deterministic query rows."""

    def __init__(
        self,
        *,
        prior_payloads: list[dict[str, object]],
        filing_rows: list[tuple[str, str, datetime]],
    ) -> None:
        self.prior_payloads = prior_payloads
        self.filing_rows = filing_rows

    def __enter__(self) -> _FilingLoaderSession:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def scalars(self, _statement: object) -> _Rows:
        return _Rows(list(self.prior_payloads))

    def execute(self, _statement: object) -> _Rows:
        return _Rows(list(self.filing_rows))


def _filing_seed(security_id: str, available_at: datetime) -> FilingCatalystSeed:
    """Build one newly indexed filing seed."""
    return FilingCatalystSeed(
        security_id=security_id,
        filing_event_ids=(f"filing-{security_id}",),
        latest_available_at=available_at,
    )
