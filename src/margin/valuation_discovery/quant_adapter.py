"""Adapter bridging the orchestrator to the quant screening service.

The orchestrator calls ``run(scope_version_id=..., decision_at=...)`` while
``QuantService.run`` expects a frozen ``QuantInputSnapshot``. This adapter
resolves the scope binding, builds the snapshot, runs quant, and returns a
result object with ``quant_run_id`` and ``results`` attributes.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Protocol

import pandas as pd

from margin.data.warehouse_repository import (
    CanonicalQuery,
    CanonicalValue,
    IndicatorHistoryQuery,
    IndicatorHistoryValue,
    IndustryQuery,
    SecurityProfileValue,
    SQLAlchemyWarehouseRepository,
)
from margin.strategy.repository import SQLAlchemyStrategyRepository
from margin.valuation_discovery.etl import (
    QuantFeatureMartETLPipeline,
    SQLAlchemyQuantFeatureMartETLPipeline,
)
from margin.valuation_discovery.models import (
    QuantInputSnapshot,
    QuantResult,
    QuantRun,
    UniverseSnapshot,
)
from margin.valuation_discovery.quant.repository import QuantRepository
from margin.valuation_discovery.quant.service import QuantService
from margin.valuation_discovery.quant_input import (
    CanonicalFactRef,
    QuantInputSnapshotBuilder,
)
from margin.valuation_discovery.scope import (
    QuantFeatureSet,
    ScopeBinding,
    UserIndicatorView,
)

HARD_FILTER_INDICATORS = ("is_suspended", "suspend_type")
MARKET_DATE_MIN_COVERAGE_RATIO = 0.8


class ScopeBindingProvider(Protocol):
    """Resolve a frozen ``ScopeBinding`` from a scope version ID."""

    def get_scope_binding(self, scope_version_id: str) -> ScopeBinding:
        """Return the scope binding for the supplied version ID."""


class WarehouseFactAdapter:
    """Adapt ``SQLAlchemyWarehouseRepository`` to ``QuantWarehouseRepository``.

    The quant input builder expects ``get_latest_fact`` to return
    ``CanonicalFactRef`` objects. The warehouse repository returns
    ``CanonicalValue`` objects which we convert on the fly.
    """

    def __init__(self, warehouse: SQLAlchemyWarehouseRepository) -> None:
        """Initialize the adapter with a SQLAlchemy warehouse repository."""
        self._warehouse = warehouse

    def get_latest_fact(
        self,
        *,
        security_id: str,
        indicator_id: str,
        known_at: datetime,
    ) -> CanonicalFactRef | None:
        """Return the latest canonical fact available at ``known_at``."""
        values = self._warehouse.canonical_values(
            CanonicalQuery(
                security_ids=(security_id,),
                indicator_ids=(indicator_id,),
                decision_at=known_at,
            )
        )
        if not values:
            return None
        value = values[0]
        return _canonical_value_to_fact_ref(value)

    def get_latest_facts(
        self,
        *,
        security_ids: tuple[str, ...],
        indicator_ids: tuple[str, ...],
        known_at: datetime,
    ) -> tuple[CanonicalFactRef, ...]:
        """Batch-load canonical fact references for a full quant universe."""
        values = self._warehouse.canonical_values(
            CanonicalQuery(
                security_ids=security_ids,
                indicator_ids=indicator_ids,
                decision_at=known_at,
            )
        )
        return tuple(_canonical_value_to_fact_ref(value) for value in values)


def _canonical_value_to_fact_ref(value: CanonicalValue) -> CanonicalFactRef:
    """Convert a ``CanonicalValue`` to a ``CanonicalFactRef``."""
    return CanonicalFactRef(
        fact_id=value.selected_fact_id or value.canonical_id,
        security_id=value.security_id,
        indicator_id=value.indicator_id,
        available_at=value.decision_at,
        payload_hash=value.resolver_hash,
    )


class SQLAlchemyScopeBindingProvider:
    """Load a ``ScopeBinding`` from strategy and warehouse repositories.

    Resolves a ``ResearchScopeVersion`` by version ID, then loads the
    referenced child versions (universe, feature set, indicator view) and
    converts them into the frozen valuation-discovery domain models.
    """

    def __init__(
        self,
        strategy_repository: SQLAlchemyStrategyRepository,
        company_pool_repository: Any | None = None,
    ) -> None:
        """Initialize the provider with strategy and optional company pool repos.

        Args:
            strategy_repository: Strategy repository for scope version loading.
            company_pool_repository: Optional company pool repository for ALL_A.
        """
        self._strategy = strategy_repository
        self._company_pool = company_pool_repository

    def get_scope_binding(self, scope_version_id: str) -> ScopeBinding:
        """Return the scope binding for the supplied version ID."""
        scope = self._strategy.get_research_scope(scope_version_id)
        if scope is None:
            raise KeyError(f"research scope not found: {scope_version_id}")

        feature_set_version = self._strategy.get_quant_feature_set(
            scope.quant_feature_set_version_id
        )
        if feature_set_version is None:
            raise KeyError(
                f"quant feature set not found: {scope.quant_feature_set_version_id}"
            )
        quant_strategy_version = self._strategy.get_quant_strategy(
            scope.quant_strategy_version_id
        )
        if quant_strategy_version is None:
            raise KeyError(
                f"quant strategy not found: {scope.quant_strategy_version_id}"
            )

        indicator_view_version = self._strategy.get_indicator_view(
            scope.indicator_view_version_id
        )
        if indicator_view_version is None:
            raise KeyError(
                f"indicator view not found: {scope.indicator_view_version_id}"
            )

        universe_version = self._strategy.get_universe_definition(
            scope.universe_version_id
        )
        if universe_version is None:
            raise KeyError(
                f"universe definition not found: {scope.universe_version_id}"
            )

        quant_feature_set = QuantFeatureSet(
            version_id=feature_set_version.version_id,
            required_indicators=feature_set_version.required_indicators,
            optional_indicators=feature_set_version.optional_indicators,
            history_days=feature_set_version.history_days,
            metadata={
                "quant_strategy": {
                    "quant_strategy_version_id": quant_strategy_version.version_id,
                    "strategy_family": quant_strategy_version.strategy_family,
                    "factor_weights": quant_strategy_version.factor_weights,
                    "thresholds": quant_strategy_version.thresholds,
                    "calibration_report_id": quant_strategy_version.calibration_report_id,
                }
            },
        )

        user_indicator_view = _build_user_indicator_view(indicator_view_version)

        pool_snapshot = (
            self._company_pool.latest()
            if self._company_pool is not None
            and str(universe_version.universe_code).upper() in {"ALL_A", "ALL_A_NON_ST"}
            else None
        )
        universe_snapshot = (
            UniverseSnapshot(
                snapshot_id=pool_snapshot.snapshot_id,
                universe_code=pool_snapshot.pool_code,
                universe_version_id=universe_version.version_id,
                business_at=pool_snapshot.business_at,
                known_at=pool_snapshot.known_at,
                security_ids=pool_snapshot.security_ids,
                membership_ids=pool_snapshot.membership_ids,
                input_hash=pool_snapshot.input_hash,
                created_at=pool_snapshot.created_at,
            )
            if pool_snapshot is not None
            else UniverseSnapshot(
                universe_code=universe_version.universe_code,
                universe_version_id=universe_version.version_id,
                business_at=datetime.now(UTC),
                known_at=datetime.now(UTC),
                security_ids=universe_version.member_security_ids,
            )
        )

        return ScopeBinding(
            scope_version_id=scope.version_id,
            universe_snapshot=universe_snapshot,
            quant_feature_set=quant_feature_set,
            user_indicator_view=user_indicator_view,
            corporate_action_adjustment_version=scope.canonical_rule_version,
            industry_snapshot_id="industry-v0.2.0",
        )


def _build_user_indicator_view(indicator_view_version: Any) -> UserIndicatorView:
    """Build a ``UserIndicatorView`` from an ``IndicatorViewVersion``."""
    from margin.strategy.models import IndicatorSelectionMode

    mode = indicator_view_version.mode
    if mode == IndicatorSelectionMode.INCLUDE:
        visible = indicator_view_version.included_indicators
        hidden: tuple[str, ...] = ()
    elif mode == IndicatorSelectionMode.EXCLUDE:
        visible = ()
        hidden = indicator_view_version.excluded_indicators
    else:
        visible = ()
        hidden = ()
    return UserIndicatorView(
        version_id=indicator_view_version.version_id,
        visible_indicator_ids=tuple(visible),
        hidden_indicator_ids=tuple(hidden),
    )


def build_cross_section_loader(
    warehouse: SQLAlchemyWarehouseRepository,
) -> Callable[[QuantInputSnapshot], pd.DataFrame]:
    """Return a cross-section loader backed by the PIT warehouse.

    The loader combines current canonical indicators with PIT-safe security
    metadata, industry membership, and historical market facts. Market-derived
    features are calculated from adjusted close and amount histories rather
    than fabricated defaults.
    """

    def loader(snapshot: QuantInputSnapshot) -> pd.DataFrame:
        """Load a PIT-safe cross-section from canonical warehouse values."""
        if not snapshot.security_ids:
            return pd.DataFrame(
                {"security_id": list(snapshot.security_ids)}
            ).set_index("security_id", drop=False)

        indicator_ids = tuple(
            dict.fromkeys(
                snapshot.required_indicators
                + snapshot.optional_indicators
                + HARD_FILTER_INDICATORS
            )
        )
        values = (
            warehouse.canonical_values(
                CanonicalQuery(
                    security_ids=snapshot.security_ids,
                    indicator_ids=indicator_ids,
                    decision_at=snapshot.decision_at,
                )
            )
            if indicator_ids
            else []
        )
        profiles = warehouse.security_profiles(
            snapshot.security_ids,
            system_as_of=snapshot.known_at,
        )
        industries = warehouse.industry_memberships(
            IndustryQuery(
                security_ids=snapshot.security_ids,
                on_date=snapshot.decision_at.date(),
                taxonomy="provider-industry",
                system_as_of=snapshot.known_at,
            )
        )
        history = warehouse.indicator_history(
            IndicatorHistoryQuery(
                security_ids=snapshot.security_ids,
                indicator_ids=("close", "amount", "adj_factor"),
                start_date=snapshot.market_window_start.date(),
                end_date=snapshot.market_window_end.date(),
                decision_at=snapshot.decision_at,
                max_points_per_indicator=260,
            )
        )
        profit_history = warehouse.indicator_history(
            IndicatorHistoryQuery(
                security_ids=snapshot.security_ids,
                indicator_ids=("n_income_attr_p",),
                start_date=snapshot.decision_at.date() - timedelta(days=1095),
                end_date=snapshot.decision_at.date(),
                decision_at=snapshot.decision_at,
                max_points_per_indicator=20,
            )
        )
        return _build_quant_cross_section(
            values=values,
            profiles=profiles,
            industries=industries,
            history=history + profit_history,
            security_ids=snapshot.security_ids,
            decision_at=snapshot.decision_at,
        )

    return loader

def _pivot_canonical_values(
    values: list[CanonicalValue],
    security_ids: tuple[str, ...],
) -> pd.DataFrame:
    """Pivot canonical values into a wide DataFrame indexed by security_id."""
    records: dict[str, dict[str, Any]] = {
        security_id: {"security_id": security_id}
        for security_id in security_ids
    }
    for value in values:
        row = records.setdefault(
            value.security_id, {"security_id": value.security_id}
        )
        numeric = value.numeric_value
        if numeric is not None:
            row[value.indicator_id] = float(numeric)
        elif value.text_value is not None:
            row[value.indicator_id] = value.text_value
        elif value.json_value is not None:
            row[value.indicator_id] = value.json_value
        else:
            row[value.indicator_id] = None
    frame = pd.DataFrame.from_dict(records, orient="index")
    frame.index = frame.index.astype(str)
    frame["security_id"] = frame.index.astype(str)
    return frame


def _build_quant_cross_section(
    *,
    values: list[CanonicalValue],
    profiles: list[SecurityProfileValue],
    industries: list[Any],
    history: list[IndicatorHistoryValue],
    security_ids: tuple[str, ...],
    decision_at: datetime,
) -> pd.DataFrame:
    """Build the production quant frame from current and historical facts."""
    frame = _pivot_canonical_values(values, security_ids)
    frame["decision_at"] = decision_at
    profile_by_security = {profile.security_id: profile for profile in profiles}
    industry_by_security = {
        membership.security_id: membership for membership in industries
    }
    for security_id in security_ids:
        profile = profile_by_security.get(security_id)
        if profile is not None:
            frame.loc[security_id, "name"] = profile.name
            frame.loc[security_id, "exchange"] = profile.exchange
            frame.loc[security_id, "listing_date"] = (
                datetime.combine(profile.listed_at, time.min, tzinfo=UTC)
                if profile.listed_at is not None
                else None
            )
            frame.loc[security_id, "is_st"] = profile.is_st
        membership = industry_by_security.get(security_id)
        industry_name = (
            membership.industry_name if membership is not None else "unknown"
        )
        frame.loc[security_id, "industry_id"] = (
            membership.industry_code if membership is not None else "unknown"
        )
        frame.loc[security_id, "industry_family"] = _industry_family(
            industry_name
        )
    if "is_suspended" in frame.columns:
        frame["is_suspended"] = frame["is_suspended"].astype("object")

    history_by_security: dict[
        str,
        dict[date, dict[str, float]],
    ] = defaultdict(lambda: defaultdict(dict))
    for value in history:
        history_by_security[value.security_id][value.event_at.date()][
            value.indicator_id
        ] = float(value.numeric_value)
    latest_market_date = _latest_covered_market_date(
        history_by_security,
        security_ids,
    )
    for security_id in security_ids:
        features, latest_security_date = _market_features(
            history_by_security.get(security_id, {}),
        )
        for field_name, value in features.items():
            frame.loc[security_id, field_name] = value
        explicit_suspension = _optional_bool(frame.loc[security_id].get("is_suspended"))
        if explicit_suspension is not None:
            frame.loc[security_id, "is_suspended"] = explicit_suspension
        else:
            frame.loc[security_id, "is_suspended"] = bool(
                latest_market_date is not None
                and (
                    latest_security_date is None
                    or latest_security_date < latest_market_date
                )
            )
        annual_profits = sorted(
            (
                event_date,
                fields["n_income_attr_p"],
            )
            for event_date, fields in history_by_security.get(
                security_id,
                {},
            ).items()
            if event_date.month == 12
            and event_date.day == 31
            and "n_income_attr_p" in fields
        )
        if annual_profits:
            frame.loc[security_id, "net_profit_y1"] = annual_profits[-1][1]
            if len(annual_profits) > 1:
                frame.loc[security_id, "net_profit_y2"] = annual_profits[-2][1]

    return_6m = pd.to_numeric(
        frame.get(
            "return_6m_ex_1m",
            pd.Series(index=frame.index, dtype=float),
        ),
        errors="coerce",
    )
    frame["index_relative_momentum"] = return_6m - return_6m.median(
        skipna=True
    )
    frame["industry_relative_momentum"] = return_6m - return_6m.groupby(
        frame["industry_id"]
    ).transform("median")
    if "is_st" not in frame.columns:
        frame["is_st"] = False
    if "is_suspended" not in frame.columns:
        frame["is_suspended"] = False
    frame["is_st"] = frame["is_st"].map(
        lambda value: False if pd.isna(value) else bool(value)
    )
    frame["is_suspended"] = frame["is_suspended"].map(
        lambda value: False if pd.isna(value) else bool(value)
    )
    return frame


def _latest_covered_market_date(
    history_by_security: dict[str, dict[date, dict[str, float]]],
    security_ids: tuple[str, ...],
) -> date | None:
    """Return the latest market date with broad close coverage."""
    if not security_ids:
        return None
    securities_by_date: dict[date, set[str]] = defaultdict(set)
    for security_id, points in history_by_security.items():
        for event_date, fields in points.items():
            close = fields.get("close")
            if close is not None and close > 0:
                securities_by_date[event_date].add(security_id)
    required_coverage = math.ceil(
        len(set(security_ids)) * MARKET_DATE_MIN_COVERAGE_RATIO
    )
    for event_date in sorted(securities_by_date, reverse=True):
        if len(securities_by_date[event_date]) >= required_coverage:
            return event_date
    return None


def _market_features(
    points: dict[date, dict[str, float]],
) -> tuple[dict[str, float], date | None]:
    """Derive liquidity, momentum, trend, and risk features."""
    if not points:
        return {}, None
    rows: list[tuple[date, float, float | None]] = []
    for event_date, fields in sorted(points.items()):
        close = fields.get("close")
        if close is None or close <= 0:
            continue
        adjusted_close = close * fields.get("adj_factor", 1.0)
        rows.append((event_date, adjusted_close, fields.get("amount")))
    if not rows:
        return {}, None
    prices = pd.Series(
        [row[1] for row in rows],
        index=pd.Index([row[0] for row in rows]),
        dtype=float,
    )
    amounts = pd.Series(
        [row[2] for row in rows],
        index=prices.index,
        dtype=float,
    )
    features: dict[str, float] = {}
    if len(prices) >= 21:
        features["return_20d"] = float(prices.iloc[-1] / prices.iloc[-21] - 1)
    if len(prices) >= 126:
        features["return_6m_ex_1m"] = float(
            prices.iloc[-21] / prices.iloc[-126] - 1
        )
    if len(prices) >= 252:
        features["return_12m_ex_1m"] = float(
            prices.iloc[-21] / prices.iloc[-252] - 1
        )
    recent_amount = amounts.dropna().tail(20)
    if not recent_amount.empty:
        features["avg_amount_20d"] = float(recent_amount.mean())
    daily_returns = prices.pct_change(fill_method=None).dropna()
    if len(daily_returns) >= 20:
        features["volatility_120d"] = float(
            daily_returns.tail(120).std(ddof=1) * math.sqrt(252)
        )
    drawdown_prices = prices.tail(250)
    if len(drawdown_prices) >= 2:
        drawdowns = drawdown_prices / drawdown_prices.cummax() - 1
        features["max_drawdown_250d"] = float(drawdowns.min())
    trend_checks: list[bool] = []
    if len(prices) >= 120:
        trend_checks.append(prices.iloc[-1] > prices.tail(120).mean())
    if len(prices) >= 250:
        trend_checks.append(prices.iloc[-1] > prices.tail(250).mean())
    if trend_checks:
        features["ma_trend"] = 100.0 * sum(trend_checks) / len(trend_checks)
    return features, rows[-1][0]


def _optional_bool(value: Any) -> bool | None:
    """Convert a warehouse boolean-like value to bool while preserving missing."""
    if value is None or bool(pd.isna(value)):
        return None
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "t", "yes", "y"}:
            return True
        if normalized in {"0", "false", "f", "no", "n"}:
            return False
    return bool(value)


def _industry_family(industry_name: str) -> str:
    """Map provider industry labels to broad hard-filter families."""
    normalized = industry_name.strip().lower()
    if any(
        marker in normalized
        for marker in ("银行", "保险", "证券", "金融", "bank", "insurance", "broker")
    ):
        return "financial"
    return normalized or "unknown"


@dataclass(frozen=True)
class QuantAdapterResult:
    """Result returned by ``QuantAdapter.run``.

    Attributes:
        quant_run_id: The persisted quant run identifier.
        results: Tuple of ``QuantResult`` for the run.
    """

    quant_run_id: str
    results: tuple[QuantResult, ...]


class QuantAdapter:
    """Adapt the orchestrator's ``run(scope_version_id=..., decision_at=...)``
    call to ``QuantService.run(snapshot, decision_at=...)``.

    The adapter resolves the scope binding, builds a frozen
    ``QuantInputSnapshot``, runs the quant screen, loads the persisted
    results, and returns a ``QuantAdapterResult``.
    """

    def __init__(
        self,
        *,
        quant_service: QuantService,
        snapshot_builder: QuantInputSnapshotBuilder,
        scope_provider: ScopeBindingProvider,
        quant_repository: QuantRepository,
        feature_mart_pipeline: (
            QuantFeatureMartETLPipeline | SQLAlchemyQuantFeatureMartETLPipeline | None
        ) = None,
        market_window_days: int = 252,
    ) -> None:
        """Initialize the adapter with quant service and supporting dependencies.

        Args:
            quant_service: The quant screening service.
            snapshot_builder: Builder for frozen quant input snapshots.
            scope_provider: Provider for frozen scope bindings.
            quant_repository: Repository for quant run and result persistence.
            feature_mart_pipeline: Optional feature mart ETL pipeline.
            market_window_days: Number of calendar days for the market window.
        """
        self._quant_service = quant_service
        self._snapshot_builder = snapshot_builder
        self._scope_provider = scope_provider
        self._quant_repository = quant_repository
        self._feature_mart_pipeline = feature_mart_pipeline
        self._market_window_days = market_window_days

    def build_input(
        self,
        *,
        scope_version_id: str,
        decision_at: datetime,
    ) -> QuantInputSnapshot:
        """Resolve the scope and persist its frozen PIT quant input.

        Args:
            scope_version_id: The frozen scope version to resolve.
            decision_at: Timezone-aware decision timestamp.

        Returns:
            A frozen ``QuantInputSnapshot`` bound to its feature snapshot.
        """
        scope = self._scope_provider.get_scope_binding(scope_version_id)
        snapshot = self._snapshot_builder.build(
            scope=scope,
            decision_at=decision_at,
            market_window_days=max(
                self._market_window_days,
                scope.quant_feature_set.history_days or 0,
            ),
            persist=self._feature_mart_pipeline is None,
        )
        if self._feature_mart_pipeline is None:
            return snapshot
        return self._feature_mart_pipeline.materialize(snapshot).input_snapshot

    def run(
        self,
        *,
        scope_version_id: str,
        decision_at: datetime,
        input_snapshot: QuantInputSnapshot | None = None,
    ) -> QuantAdapterResult:
        """Build a snapshot, run quant, and return a result with results.

        Args:
            scope_version_id: The frozen scope version to screen.
            decision_at: Timezone-aware decision timestamp.
            input_snapshot: Optional pre-built snapshot; built if not supplied.

        Returns:
            QuantAdapterResult with the quant run ID and persisted results.
        """
        snapshot = input_snapshot or self.build_input(
            scope_version_id=scope_version_id,
            decision_at=decision_at,
        )
        quant_run: QuantRun = self._quant_service.run(
            snapshot, decision_at=decision_at
        )
        results = self._quant_repository.list_results(quant_run.quant_run_id)
        return QuantAdapterResult(
            quant_run_id=quant_run.quant_run_id,
            results=results,
        )

    def load_input(self, snapshot_id: str) -> QuantInputSnapshot:
        """Reload a persisted frozen input snapshot by output reference.

        Args:
            snapshot_id: The persisted snapshot ID.

        Returns:
            The reloaded ``QuantInputSnapshot``.

        Raises:
            KeyError: If the snapshot is not found.
        """
        snapshot = self._snapshot_builder.get(snapshot_id)
        if snapshot is None:
            raise KeyError(f"quant input snapshot not found: {snapshot_id}")
        return snapshot

    def load_run(self, quant_run_id: str) -> QuantAdapterResult:
        """Reload a persisted quant run and its complete result set.

        Args:
            quant_run_id: The persisted quant run ID.

        Returns:
            QuantAdapterResult with the quant run ID and persisted results.

        Raises:
            KeyError: If the quant run is not found.
        """
        quant_run = self._quant_repository.get_run(quant_run_id)
        if quant_run is None:
            raise KeyError(f"quant run not found: {quant_run_id}")
        return QuantAdapterResult(
            quant_run_id=quant_run.quant_run_id,
            results=self._quant_repository.list_results(quant_run.quant_run_id),
        )
