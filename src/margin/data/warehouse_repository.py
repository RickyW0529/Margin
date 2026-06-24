"""Point-in-time read contracts for downstream quant and research modules."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from margin.data.db_models import (
    AdjustedPriceSeriesRow,
    CanonicalIndicatorValueRow,
    DataFreshnessStateRow,
    DataQualityEventRow,
    SecurityIndustryMembershipRow,
)
from margin.data.freshness import DataDomain, FreshnessStatus
from margin.news.models import ensure_utc
from margin.sql.data_queries import (
    adjusted_prices_by_decision,
    canonical_values_by_decision,
    freshness_records,
    indicator_history_pit,
    industry_memberships_bitemporal,
    quality_events_recent,
    security_profiles_active,
)


class PITQueryError(ValueError):
    """Raised when a historical warehouse query omits PIT parameters."""


@dataclass(frozen=True)
class CanonicalQuery:
    """Query canonical indicator values as known at ``decision_at``."""

    security_ids: tuple[str, ...]
    indicator_ids: tuple[str, ...] = ()
    decision_at: datetime | None = None


@dataclass(frozen=True)
class CanonicalValue:
    """Canonical indicator value selected from provider candidates."""

    canonical_id: str
    security_id: str
    indicator_id: str
    decision_at: datetime
    status: str
    selected_fact_id: str | None
    candidate_fact_ids: tuple[str, ...]
    numeric_value: Decimal | None
    text_value: str | None
    json_value: dict | None
    confidence: Decimal
    resolver_version: str
    resolver_hash: str


@dataclass(frozen=True)
class IndustryQuery:
    """Query bitemporal industry membership."""

    security_ids: tuple[str, ...]
    on_date: date
    taxonomy: str
    system_as_of: datetime | None = None


@dataclass(frozen=True)
class IndustryMembershipValue:
    """Industry membership as known at a system time."""

    membership_id: str
    security_id: str
    taxonomy: str
    industry_code: str
    industry_name: str
    valid_from: date
    valid_to: date | None
    system_from: datetime
    system_to: datetime | None
    source: str
    quality: str


@dataclass(frozen=True)
class AdjustedPriceQuery:
    """Query as-of adjusted prices."""

    security_ids: tuple[str, ...]
    start_date: date
    end_date: date
    decision_at: datetime | None = None


@dataclass(frozen=True)
class AdjustedPriceValue:
    """As-of adjusted price point."""

    security_id: str
    trade_date: date
    decision_at: datetime
    close: Decimal
    adj_close: Decimal
    adjustment_factor: Decimal
    adjustment_policy_version: str
    input_hash: str


@dataclass(frozen=True)
class FreshnessRecord:
    """Persisted freshness state."""

    provider: str
    endpoint_code: str
    as_of_date: date
    expected_at: datetime | None
    observed_at: datetime | None
    status: FreshnessStatus
    lag_seconds: int | None


@dataclass(frozen=True)
class QualityEventQuery:
    """Query append-only data-quality events."""

    security_ids: tuple[str, ...] = ()
    since: datetime | None = None


@dataclass(frozen=True)
class QualityEvent:
    """Data-quality event visible to downstream modules."""

    event_id: str
    security_id: str | None
    indicator_id: str | None
    issue_type: str
    severity: str
    message: str
    observed: dict
    created_at: datetime


@dataclass(frozen=True)
class MarketWindowQuery:
    """Placeholder-compatible query for downstream market reads.

    Raw market bars will be materialized in a later implementation task; for now
    downstream PIT price reads use ``AdjustedPriceQuery``.
    """

    security_ids: tuple[str, ...]
    start_date: date
    end_date: date
    decision_at: datetime | None = None


@dataclass(frozen=True)
class SecurityProfileValue:
    """Security-master attributes known at a system time."""

    security_id: str
    symbol: str
    name: str
    exchange: str
    listed_at: date | None
    delisted_at: date | None
    is_st: bool


@dataclass(frozen=True)
class IndicatorHistoryQuery:
    """Query historical numeric indicator facts with PIT enforcement."""

    security_ids: tuple[str, ...]
    indicator_ids: tuple[str, ...]
    start_date: date
    end_date: date
    decision_at: datetime | None = None
    max_points_per_indicator: int | None = None


@dataclass(frozen=True)
class IndicatorHistoryValue:
    """One canonicalized historical numeric fact for a business timestamp."""

    fact_id: str
    provider: str
    security_id: str
    indicator_id: str
    event_at: datetime
    available_at: datetime
    fetched_at: datetime
    numeric_value: Decimal
    quality_score: Decimal


class SQLAlchemyWarehouseRepository:
    """PIT-safe warehouse repository backed by SQLAlchemy."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        """Initialize the instance."""
        self._session_factory = session_factory

    def canonical_values(self, query: CanonicalQuery) -> list[CanonicalValue]:
        """Return latest canonical values known at ``query.decision_at``."""
        decision_at = _require_decision_at(query.decision_at)
        if not query.security_ids:
            return []
        with self._session_factory() as session:
            statement = canonical_values_by_decision(
                security_ids=query.security_ids,
                decision_at=decision_at,
                indicator_ids=query.indicator_ids or None,
            )
            rows = session.scalars(statement).all()
        latest: dict[tuple[str, str], CanonicalValue] = {}
        for row in rows:
            key = (row.security_id, row.indicator_id)
            latest.setdefault(key, _canonical_value_from_row(row))
        return list(latest.values())

    def market_window(self, query: MarketWindowQuery) -> list[AdjustedPriceValue]:
        """Return adjusted prices for the requested PIT market window."""
        return self.adjusted_prices(
            AdjustedPriceQuery(
                security_ids=query.security_ids,
                start_date=query.start_date,
                end_date=query.end_date,
                decision_at=query.decision_at,
            )
        )

    def industry_memberships(self, query: IndustryQuery) -> list[IndustryMembershipValue]:
        """Return industry memberships valid at business and system time."""
        system_as_of = _require_system_as_of(query.system_as_of)
        if not query.security_ids:
            return []
        with self._session_factory() as session:
            rows = session.scalars(
                industry_memberships_bitemporal(
                    security_ids=query.security_ids,
                    on_date=query.on_date,
                    taxonomy=query.taxonomy,
                    system_as_of=system_as_of,
                )
            ).all()
        latest: dict[str, IndustryMembershipValue] = {}
        for row in rows:
            latest.setdefault(row.security_id, _industry_from_row(row))
        return list(latest.values())

    def adjusted_prices(self, query: AdjustedPriceQuery) -> list[AdjustedPriceValue]:
        """Return latest adjusted prices known at ``query.decision_at``."""
        decision_at = _require_decision_at(query.decision_at)
        if not query.security_ids:
            return []
        with self._session_factory() as session:
            rows = session.scalars(
                adjusted_prices_by_decision(
                    security_ids=query.security_ids,
                    start_date=query.start_date,
                    end_date=query.end_date,
                    decision_at=decision_at,
                )
            ).all()
        latest: dict[tuple[str, date], AdjustedPriceValue] = {}
        for row in rows:
            latest.setdefault((row.security_id, row.trade_date), _adjusted_price_from_row(row))
        return list(latest.values())

    def freshness(self, domains: set[DataDomain | str] | None = None) -> list[FreshnessRecord]:
        """Return persisted freshness records.

        Results contain only the latest as-of row for each provider endpoint.
        Domain filtering joins the endpoint registry instead of guessing from
        endpoint names.
        """
        normalized_domains = {DataDomain(domain).value for domain in domains or set()}
        statement = freshness_records(normalized_domains or None)
        with self._session_factory() as session:
            rows = session.scalars(statement).all()
        latest: dict[tuple[str, str], FreshnessRecord] = {}
        for row in rows:
            latest.setdefault(
                (row.provider, row.endpoint_code),
                _freshness_from_row(row),
            )
        return list(latest.values())

    def quality_events(self, query: QualityEventQuery) -> list[QualityEvent]:
        """Return append-only quality events."""
        statement = quality_events_recent(
            security_ids=query.security_ids,
            since=ensure_utc(query.since) if query.since is not None else None,
        )
        with self._session_factory() as session:
            rows = session.scalars(statement).all()
        return [_quality_event_from_row(row) for row in rows]

    def security_profiles(
        self,
        security_ids: tuple[str, ...],
        *,
        system_as_of: datetime,
    ) -> list[SecurityProfileValue]:
        """Return active security-master records known at ``system_as_of``."""
        known_at = _require_system_as_of(system_as_of)
        if not security_ids:
            return []
        with self._session_factory() as session:
            rows = session.scalars(
                security_profiles_active(
                    security_ids=security_ids,
                    system_as_of=known_at,
                )
            ).all()
        latest: dict[str, SecurityProfileValue] = {}
        for row in rows:
            latest.setdefault(
                row.security_id,
                SecurityProfileValue(
                    security_id=row.security_id,
                    symbol=row.symbol,
                    name=row.name,
                    exchange=row.exchange,
                    listed_at=row.listed_at,
                    delisted_at=row.delisted_at,
                    is_st="ST" in row.name.upper(),
                ),
            )
        return list(latest.values())

    def indicator_history(
        self,
        query: IndicatorHistoryQuery,
    ) -> list[IndicatorHistoryValue]:
        """Return one deterministic provider fact per security/indicator/event."""
        decision_at = _require_decision_at(query.decision_at)
        if not query.security_ids or not query.indicator_ids:
            return []
        with self._session_factory() as session:
            statement = indicator_history_pit(
                security_ids=query.security_ids,
                indicator_ids=query.indicator_ids,
                start_date=query.start_date,
                end_date=query.end_date,
                decision_at=decision_at,
                max_points_per_indicator=query.max_points_per_indicator,
            )
            rows = session.execute(statement).mappings().all()
        return [
            IndicatorHistoryValue(
                fact_id=row.fact_id,
                provider=row.provider,
                security_id=row.security_id,
                indicator_id=row.indicator_id,
                event_at=row.event_at,
                available_at=row.available_at,
                fetched_at=row.fetched_at,
                numeric_value=row.numeric_value,
                quality_score=row.quality_score,
            )
            for row in rows
        ]


def _require_decision_at(value: datetime | None) -> datetime:
    """require decision at."""
    if value is None:
        raise PITQueryError("decision_at is required for PIT warehouse queries")
    return ensure_utc(value)


def _require_system_as_of(value: datetime | None) -> datetime:
    """require system as of."""
    if value is None:
        raise PITQueryError("system_as_of is required for bitemporal warehouse queries")
    return ensure_utc(value)


def _canonical_value_from_row(row: CanonicalIndicatorValueRow) -> CanonicalValue:
    """canonical value from row."""
    return CanonicalValue(
        canonical_id=row.canonical_id,
        security_id=row.security_id,
        indicator_id=row.indicator_id,
        decision_at=row.decision_at,
        status=row.status,
        selected_fact_id=row.selected_fact_id,
        candidate_fact_ids=tuple(row.candidate_fact_ids),
        numeric_value=row.numeric_value,
        text_value=row.text_value,
        json_value=row.json_value,
        confidence=row.confidence,
        resolver_version=row.resolver_version,
        resolver_hash=row.resolver_hash,
    )


def _industry_from_row(row: SecurityIndustryMembershipRow) -> IndustryMembershipValue:
    """industry from row."""
    return IndustryMembershipValue(
        membership_id=row.membership_id,
        security_id=row.security_id,
        taxonomy=row.taxonomy,
        industry_code=row.industry_code,
        industry_name=row.industry_name,
        valid_from=row.valid_from,
        valid_to=row.valid_to,
        system_from=row.system_from,
        system_to=row.system_to,
        source=row.source,
        quality=row.quality,
    )


def _adjusted_price_from_row(row: AdjustedPriceSeriesRow) -> AdjustedPriceValue:
    """adjusted price from row."""
    return AdjustedPriceValue(
        security_id=row.security_id,
        trade_date=row.trade_date,
        decision_at=row.decision_at,
        close=row.close,
        adj_close=row.adj_close,
        adjustment_factor=row.adjustment_factor,
        adjustment_policy_version=row.adjustment_policy_version,
        input_hash=row.input_hash,
    )


def _freshness_from_row(row: DataFreshnessStateRow) -> FreshnessRecord:
    """freshness from row."""
    return FreshnessRecord(
        provider=row.provider,
        endpoint_code=row.endpoint_code,
        as_of_date=row.as_of_date,
        expected_at=row.expected_at,
        observed_at=row.observed_at,
        status=FreshnessStatus(row.status),
        lag_seconds=row.lag_seconds,
    )


def _quality_event_from_row(row: DataQualityEventRow) -> QualityEvent:
    """quality event from row."""
    return QualityEvent(
        event_id=row.event_id,
        security_id=row.security_id,
        indicator_id=row.indicator_id,
        issue_type=row.issue_type,
        severity=row.severity,
        message=row.message,
        observed=row.observed,
        created_at=row.created_at,
    )
