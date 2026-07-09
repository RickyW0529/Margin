"""Production quant cross-section adapter tests.

This module validates that the cross-section loader derives PIT metadata and
market features, the feature mart loader reads materialized cross sections,
and the ETL pipeline binds the snapshot before quant reads.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pandas as pd

from margin.data.warehouse_repository import (
    CanonicalValue,
    IndicatorHistoryQuery,
    IndicatorHistoryValue,
    IndustryMembershipValue,
    SecurityProfileValue,
)
from margin.valuation_discovery.analysis_mart import MemoryAnalysisMartRepository
from margin.valuation_discovery.etl import (
    QuantFeatureMartETLPipeline,
    build_feature_mart_cross_section_loader,
    publish_quant_feature_snapshot,
)
from margin.valuation_discovery.models import QuantInputSnapshot
from margin.valuation_discovery.quant_adapter import (
    build_cross_section_loader,
)

DECISION_AT = datetime(2026, 6, 22, tzinfo=UTC)


class FakeWarehouse:
    """Warehouse double exposing the production loader contract.."""

    def __init__(self) -> None:
        """Initialize deterministic current and historical facts.

        Returns:
            None: .
        """
        self.history_query: IndicatorHistoryQuery | None = None
        self.history_queries: list[IndicatorHistoryQuery] = []
        self._dates = [
            value.date() for value in pd.bdate_range(end=DECISION_AT.date(), periods=260)
        ]

    def canonical_values(self, _query):
        """Return current financial and valuation indicators.

        Args:
            _query: Any: .

        Returns:
            Any: .
        """
        values = [
            _canonical("000001.SZ", "roe_ttm", "0.15"),
            _canonical("000001.SZ", "n_income_attr_p", "100"),
            _canonical("000001.SZ", "pe_ttm", "10"),
            _canonical_text(
                "000001.SZ",
                "audit_opinion",
                "standard_unqualified",
            ),
            _canonical("000002.SZ", "roe_ttm", "0.08"),
            _canonical("000002.SZ", "n_income_attr_p", "-10"),
            _canonical("000002.SZ", "pe_ttm", "20"),
        ]
        if "is_suspended" in _query.indicator_ids:
            values.append(_canonical("000002.SZ", "is_suspended", "1"))
        return values

    def security_profiles(self, _security_ids, *, system_as_of):
        """Return PIT security metadata.

        Args:
            _security_ids: Any: .
            system_as_of: Any: .

        Returns:
            Any: .
        """
        assert system_as_of == DECISION_AT
        return [
            SecurityProfileValue(
                security_id="000001.SZ",
                symbol="000001.SZ",
                name="平安银行",
                exchange="SZ",
                listed_at=date(1991, 4, 3),
                delisted_at=None,
                is_st=False,
            ),
            SecurityProfileValue(
                security_id="000002.SZ",
                symbol="000002.SZ",
                name="ST示例",
                exchange="SZ",
                listed_at=date(2000, 1, 1),
                delisted_at=None,
                is_st=True,
            ),
        ]

    def industry_memberships(self, _query):
        """Return provider-industry membership.

        Args:
            _query: Any: .

        Returns:
            Any: .
        """
        return [
            _industry("000001.SZ", "银行"),
            _industry("000002.SZ", "软件服务"),
        ]

    def indicator_history(self, query):
        """Return PIT-safe daily market facts or annual raw profit facts.

        Args:
            query: Any: .

        Returns:
            Any: .
        """
        self.history_queries.append(query)
        if query.indicator_ids == ("n_income_attr_p",):
            return [
                _income_fact("000001.SZ", date(2024, 12, 31), 80.0),
                _income_fact("000001.SZ", date(2025, 12, 31), 100.0),
                _income_fact("000002.SZ", date(2024, 12, 31), -20.0),
                _income_fact("000002.SZ", date(2025, 12, 31), -10.0),
            ]
        self.history_query = query
        result: list[IndicatorHistoryValue] = []
        for index, business_date in enumerate(self._dates):
            result.extend(
                _market_facts(
                    "000001.SZ",
                    business_date,
                    close=10.0 + index * 0.05,
                    amount=100_000_000,
                )
            )
            if business_date != self._dates[-1]:
                result.extend(
                    _market_facts(
                        "000002.SZ",
                        business_date,
                        close=20.0 - index * 0.01,
                        amount=80_000_000,
                    )
                )
        return result


def test_loader_builds_pit_metadata_and_market_features() -> None:
    """Verify the loader derives real quant inputs and marks stale market histories.

    Returns:
        None: .
    """
    warehouse = FakeWarehouse()
    snapshot = QuantInputSnapshot(
        scope_version_id="scope-v1",
        universe_snapshot_id="universe-v1",
        decision_at=DECISION_AT,
        known_at=DECISION_AT,
        security_ids=("000001.SZ", "000002.SZ"),
        required_indicators=("n_income_attr_p", "roe_ttm", "pe_ttm"),
        optional_indicators=("audit_opinion",),
        market_window_start=datetime(2025, 1, 1, tzinfo=UTC),
        market_window_end=DECISION_AT,
    )

    frame = build_cross_section_loader(warehouse)(snapshot)

    assert frame.loc["000001.SZ", "roe_ttm"] == 0.15
    assert frame.loc["000001.SZ", "audit_opinion"] == "standard_unqualified"
    assert frame.loc["000001.SZ", "industry_family"] == "financial"
    assert frame.loc["000001.SZ", "avg_amount_20d"] == 100_000_000
    assert frame.loc["000001.SZ", "net_profit_y1"] == 100.0
    assert frame.loc["000001.SZ", "net_profit_y2"] == 80.0
    assert frame.loc["000002.SZ", "net_profit_y1"] == -10.0
    assert frame.loc["000002.SZ", "net_profit_y2"] == -20.0
    assert frame.loc["000001.SZ", "return_20d"] > 0
    assert frame.loc["000001.SZ", "return_12m_ex_1m"] > 0
    assert not bool(frame.loc["000001.SZ", "is_suspended"])
    assert bool(frame.loc["000002.SZ", "is_st"])
    assert bool(frame.loc["000002.SZ", "is_suspended"])
    assert len(warehouse.history_queries) == 2
    market_query, profit_query = warehouse.history_queries
    assert market_query.decision_at == DECISION_AT
    assert set(market_query.indicator_ids) == {
        "close",
        "amount",
        "adj_factor",
    }
    assert profit_query.decision_at == DECISION_AT
    assert profit_query.indicator_ids == ("n_income_attr_p",)
    assert profit_query.max_points_per_indicator == 20


def test_feature_mart_loader_reads_materialized_cross_section() -> None:
    """Verify third-layer ETL writes fourth-layer features consumed by quant.

    Returns:
        None: .
    """
    warehouse = FakeWarehouse()
    repository = MemoryAnalysisMartRepository()
    snapshot = QuantInputSnapshot(
        scope_version_id="scope-v1",
        universe_snapshot_id="universe-v1",
        decision_at=DECISION_AT,
        known_at=DECISION_AT,
        security_ids=("000001.SZ", "000002.SZ"),
        required_indicators=("n_income_attr_p", "roe_ttm", "pe_ttm"),
        optional_indicators=("audit_opinion",),
        market_window_start=datetime(2025, 1, 1, tzinfo=UTC),
        market_window_end=DECISION_AT,
    )
    frame = build_cross_section_loader(warehouse)(snapshot)

    feature_snapshot = publish_quant_feature_snapshot(
        repository=repository,
        snapshot=snapshot,
        frame=frame,
    )
    bound_snapshot = QuantInputSnapshot(
        **{
            **snapshot.model_dump(),
            "feature_snapshot_id": feature_snapshot.feature_snapshot_id,
        }
    )

    loaded = build_feature_mart_cross_section_loader(repository)(bound_snapshot)

    assert bound_snapshot.feature_snapshot_id == feature_snapshot.feature_snapshot_id
    assert loaded.loc["000001.SZ", "pe_ttm"] == 10.0
    assert loaded.loc["000001.SZ", "net_profit_y1"] == 100.0
    assert loaded.loc["000001.SZ", "net_profit_y2"] == 80.0
    assert loaded.loc["000001.SZ", "avg_amount_20d"] == 100_000_000
    assert loaded.loc["000001.SZ", "return_12m_ex_1m"] > 0
    assert bool(loaded.loc["000002.SZ", "is_st"])
    assert bool(loaded.loc["000002.SZ", "is_suspended"])


def test_feature_mart_etl_pipeline_binds_snapshot_before_quant_read() -> None:
    """Verify managed ETL returns a quant input bound to the fourth-layer feature set.
    Returns:.

    Returns:
        None: .
    """
    warehouse = FakeWarehouse()
    repository = MemoryAnalysisMartRepository()
    snapshot = QuantInputSnapshot(
        scope_version_id="scope-v1",
        universe_snapshot_id="universe-v1",
        decision_at=DECISION_AT,
        known_at=DECISION_AT,
        security_ids=("000001.SZ", "000002.SZ"),
        required_indicators=("n_income_attr_p", "roe_ttm", "pe_ttm"),
        optional_indicators=("audit_opinion",),
        market_window_start=datetime(2025, 1, 1, tzinfo=UTC),
        market_window_end=DECISION_AT,
    )
    pipeline = QuantFeatureMartETLPipeline(
        repository=repository,
        source_loader=build_cross_section_loader(warehouse),
    )

    result = pipeline.materialize(snapshot)
    loaded = build_feature_mart_cross_section_loader(repository)(result.input_snapshot)

    assert result.input_snapshot.feature_snapshot_id == (
        result.feature_snapshot.feature_snapshot_id
    )
    assert repository.get_feature_snapshot(result.feature_snapshot.feature_snapshot_id)
    assert loaded.loc["000001.SZ", "pe_ttm"] == 10.0
    assert loaded.loc["000001.SZ", "net_profit_y1"] == 100.0


def test_loader_uses_explicit_suspension_status_without_feature_set_opt_in() -> None:
    """Verify suspend_d-derived status is part of the hard-filter contract.

    Returns:
        None: .
    """
    warehouse = ExplicitSuspensionWarehouse()
    snapshot = QuantInputSnapshot(
        scope_version_id="scope-v1",
        universe_snapshot_id="universe-v1",
        decision_at=DECISION_AT,
        known_at=DECISION_AT,
        security_ids=("000001.SZ", "000002.SZ"),
        required_indicators=("n_income_attr_p", "roe_ttm", "pe_ttm"),
        optional_indicators=(),
        market_window_start=datetime(2025, 1, 1, tzinfo=UTC),
        market_window_end=DECISION_AT,
    )

    frame = build_cross_section_loader(warehouse)(snapshot)

    assert "is_suspended" in warehouse.current_indicator_ids
    assert not bool(frame.loc["000001.SZ", "is_suspended"])
    assert bool(frame.loc["000002.SZ", "is_suspended"])


def test_loader_ignores_partial_latest_market_date_for_suspension_fallback() -> None:
    """Verify one stray latest bar does not mark the whole market suspended.

    Returns:
        None: .
    """
    warehouse = PartialLatestMarketWarehouse()
    snapshot = QuantInputSnapshot(
        scope_version_id="scope-v1",
        universe_snapshot_id="universe-v1",
        decision_at=DECISION_AT,
        known_at=DECISION_AT,
        security_ids=("000001.SZ", "000002.SZ", "000003.SZ"),
        required_indicators=("n_income_attr_p", "roe_ttm", "pe_ttm"),
        optional_indicators=(),
        market_window_start=datetime(2025, 1, 1, tzinfo=UTC),
        market_window_end=DECISION_AT,
    )

    frame = build_cross_section_loader(warehouse)(snapshot)

    assert not bool(frame.loc["000001.SZ", "is_suspended"])
    assert not bool(frame.loc["000002.SZ", "is_suspended"])
    assert not bool(frame.loc["000003.SZ", "is_suspended"])


class ExplicitSuspensionWarehouse(FakeWarehouse):
    """Warehouse double that only returns suspension status when requested.."""

    def __init__(self) -> None:
        """Initialize current indicator tracking.

        Returns:
            None: .
        """
        super().__init__()
        self.current_indicator_ids: tuple[str, ...] = ()

    def canonical_values(self, query):
        """Return explicit suspension facts only when loader asks for them.

        Args:
            query: Any: .

        Returns:
            Any: .
        """
        self.current_indicator_ids = query.indicator_ids
        return list(super().canonical_values(query))

    def indicator_history(self, query):
        """Return full market coverage so only explicit status can suspend.

        Args:
            query: Any: .

        Returns:
            Any: .
        """
        self.history_queries.append(query)
        if query.indicator_ids == ("n_income_attr_p",):
            return super().indicator_history(query)
        self.history_query = query
        result: list[IndicatorHistoryValue] = []
        for index, business_date in enumerate(self._dates):
            for security_id in ("000001.SZ", "000002.SZ"):
                result.extend(
                    _market_facts(
                        security_id,
                        business_date,
                        close=10.0 + index * 0.05,
                        amount=100_000_000,
                    )
                )
        return result


class PartialLatestMarketWarehouse(FakeWarehouse):
    """Warehouse double with one low-coverage latest market date.."""

    def canonical_values(self, query):
        """Return current indicators for three securities.

        Args:
            query: Any: .

        Returns:
            Any: .
        """
        return [
            _canonical("000001.SZ", "roe_ttm", "0.15"),
            _canonical("000001.SZ", "n_income_attr_p", "100"),
            _canonical("000001.SZ", "pe_ttm", "10"),
            _canonical("000002.SZ", "roe_ttm", "0.08"),
            _canonical("000002.SZ", "n_income_attr_p", "80"),
            _canonical("000002.SZ", "pe_ttm", "20"),
            _canonical("000003.SZ", "roe_ttm", "0.12"),
            _canonical("000003.SZ", "n_income_attr_p", "50"),
            _canonical("000003.SZ", "pe_ttm", "15"),
        ]

    def security_profiles(self, _security_ids, *, system_as_of):
        """Return three active non-ST profiles.

        Args:
            _security_ids: Any: .
            system_as_of: Any: .

        Returns:
            Any: .
        """
        return [
            SecurityProfileValue(
                security_id="000001.SZ",
                symbol="000001.SZ",
                name="平安银行",
                exchange="SZ",
                listed_at=date(1991, 4, 3),
                delisted_at=None,
                is_st=False,
            ),
            SecurityProfileValue(
                security_id="000002.SZ",
                symbol="000002.SZ",
                name="万科A",
                exchange="SZ",
                listed_at=date(1991, 1, 29),
                delisted_at=None,
                is_st=False,
            ),
            SecurityProfileValue(
                security_id="000003.SZ",
                symbol="000003.SZ",
                name="示例三",
                exchange="SZ",
                listed_at=date(2000, 1, 1),
                delisted_at=None,
                is_st=False,
            ),
        ]

    def industry_memberships(self, _query):
        """Return provider-industry membership for three securities.

        Args:
            _query: Any: .

        Returns:
            Any: .
        """
        return [
            _industry("000001.SZ", "银行"),
            _industry("000002.SZ", "房地产"),
            _industry("000003.SZ", "软件服务"),
        ]

    def indicator_history(self, query):
        """Return full prior coverage plus one partial latest date.

        Args:
            query: Any: .

        Returns:
            Any: .
        """
        self.history_queries.append(query)
        if query.indicator_ids == ("n_income_attr_p",):
            return [
                _income_fact("000001.SZ", date(2025, 12, 31), 100.0),
                _income_fact("000002.SZ", date(2025, 12, 31), 80.0),
                _income_fact("000003.SZ", date(2025, 12, 31), 50.0),
            ]
        self.history_query = query
        previous_date = DECISION_AT.date()
        partial_date = date(2026, 6, 23)
        result: list[IndicatorHistoryValue] = []
        for security_id in ("000001.SZ", "000002.SZ", "000003.SZ"):
            result.extend(
                _market_facts(
                    security_id,
                    previous_date,
                    close=10.0,
                    amount=100_000_000,
                )
            )
        result.extend(
            _market_facts(
                "000001.SZ",
                partial_date,
                close=10.1,
                amount=100_000_000,
            )
        )
        return result


def _canonical(
    security_id: str,
    indicator_id: str,
    value: str,
) -> CanonicalValue:
    """Build one current canonical value.

    Args:
        security_id: str: .
        indicator_id: str: .
        value: str: .

    Returns:
        CanonicalValue: .
    """
    return CanonicalValue(
        canonical_id=f"cv-{security_id}-{indicator_id}",
        security_id=security_id,
        indicator_id=indicator_id,
        decision_at=DECISION_AT,
        status="resolved",
        selected_fact_id=f"fact-{security_id}-{indicator_id}",
        candidate_fact_ids=(f"fact-{security_id}-{indicator_id}",),
        numeric_value=Decimal(value),
        text_value=None,
        json_value=None,
        confidence=Decimal("0.9"),
        resolver_version="resolver-v1",
        resolver_hash="sha256:test",
    )


def _canonical_text(
    security_id: str,
    indicator_id: str,
    value: str,
) -> CanonicalValue:
    """Build one current canonical text value.

    Args:
        security_id: str: .
        indicator_id: str: .
        value: str: .

    Returns:
        CanonicalValue: .
    """
    canonical = _canonical(security_id, indicator_id, "0")
    return CanonicalValue(
        **{
            **canonical.__dict__,
            "numeric_value": None,
            "text_value": value,
        }
    )


def _industry(
    security_id: str,
    industry_name: str,
) -> IndustryMembershipValue:
    """Build one active industry membership.

    Args:
        security_id: str: .
        industry_name: str: .

    Returns:
        IndustryMembershipValue: .
    """
    return IndustryMembershipValue(
        membership_id=f"membership-{security_id}",
        security_id=security_id,
        taxonomy="provider-industry",
        industry_code=industry_name,
        industry_name=industry_name,
        valid_from=date(2020, 1, 1),
        valid_to=None,
        system_from=datetime(2020, 1, 1, tzinfo=UTC),
        system_to=None,
        source="tushare",
        quality="provider_reported",
    )


def _market_facts(
    security_id: str,
    business_date: date,
    *,
    close: float,
    amount: float,
) -> list[IndicatorHistoryValue]:
    """Build close and amount historical facts.

    Args:
        security_id: str: .
        business_date: date: .
        close: float: .
        amount: float: .

    Returns:
        list[IndicatorHistoryValue]: .
    """
    event_at = datetime.combine(
        business_date,
        datetime.min.time(),
        tzinfo=UTC,
    )
    return [
        IndicatorHistoryValue(
            fact_id=f"{security_id}-{business_date}-close",
            provider="tushare",
            security_id=security_id,
            indicator_id="close",
            event_at=event_at,
            available_at=event_at,
            fetched_at=DECISION_AT,
            numeric_value=Decimal(str(close)),
            quality_score=Decimal("0.9"),
        ),
        IndicatorHistoryValue(
            fact_id=f"{security_id}-{business_date}-amount",
            provider="tushare",
            security_id=security_id,
            indicator_id="amount",
            event_at=event_at,
            available_at=event_at,
            fetched_at=DECISION_AT,
            numeric_value=Decimal(str(amount)),
            quality_score=Decimal("0.9"),
        ),
    ]


def _income_fact(
    security_id: str,
    report_date: date,
    profit: float,
) -> IndicatorHistoryValue:
    """Build one annual raw parent-company profit historical fact.

    Args:
        security_id: str: .
        report_date: date: .
        profit: float: .

    Returns:
        IndicatorHistoryValue: .
    """
    event_at = datetime.combine(
        report_date,
        datetime.min.time(),
        tzinfo=UTC,
    )
    return IndicatorHistoryValue(
        fact_id=f"{security_id}-{report_date}-n-income-attr-p",
        provider="tushare",
        security_id=security_id,
        indicator_id="n_income_attr_p",
        event_at=event_at,
        available_at=event_at,
        fetched_at=DECISION_AT,
        numeric_value=Decimal(str(profit)),
        quality_score=Decimal("0.9"),
    )
