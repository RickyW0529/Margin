"""Production quant cross-section adapter tests."""

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
    """Warehouse double exposing the production loader contract."""

    def __init__(self) -> None:
        """Initialize deterministic current and historical facts."""
        self.history_query: IndicatorHistoryQuery | None = None
        self._dates = [
            value.date()
            for value in pd.bdate_range(end=DECISION_AT.date(), periods=260)
        ]

    def canonical_values(self, _query):
        """Return current financial and valuation indicators."""
        return [
            _canonical("000001.SZ", "roe_ttm", "0.15"),
            _canonical("000001.SZ", "net_profit_ttm", "100"),
            _canonical("000001.SZ", "pe_ttm", "10"),
            _canonical_text(
                "000001.SZ",
                "audit_opinion",
                "standard_unqualified",
            ),
            _canonical("000002.SZ", "roe_ttm", "0.08"),
            _canonical("000002.SZ", "net_profit_ttm", "80"),
            _canonical("000002.SZ", "pe_ttm", "20"),
        ]

    def security_profiles(self, _security_ids, *, system_as_of):
        """Return PIT security metadata."""
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
        """Return provider-industry membership."""
        return [
            _industry("000001.SZ", "银行"),
            _industry("000002.SZ", "软件服务"),
        ]

    def indicator_history(self, query):
        """Return 260 PIT-safe daily close/amount facts."""
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
    """Loader derives real quant inputs and marks stale market histories."""
    warehouse = FakeWarehouse()
    snapshot = QuantInputSnapshot(
        scope_version_id="scope-v1",
        universe_snapshot_id="universe-v1",
        decision_at=DECISION_AT,
        known_at=DECISION_AT,
        security_ids=("000001.SZ", "000002.SZ"),
        required_indicators=("net_profit_ttm", "pe_ttm"),
        optional_indicators=("roe_ttm", "audit_opinion"),
        market_window_start=datetime(2025, 1, 1, tzinfo=UTC),
        market_window_end=DECISION_AT,
    )

    frame = build_cross_section_loader(warehouse)(snapshot)

    assert frame.loc["000001.SZ", "roe_ttm"] == 0.15
    assert frame.loc["000001.SZ", "audit_opinion"] == "standard_unqualified"
    assert frame.loc["000001.SZ", "industry_family"] == "financial"
    assert frame.loc["000001.SZ", "avg_amount_20d"] == 100_000_000
    assert frame.loc["000001.SZ", "return_20d"] > 0
    assert frame.loc["000001.SZ", "return_12m_ex_1m"] > 0
    assert not bool(frame.loc["000001.SZ", "is_suspended"])
    assert bool(frame.loc["000002.SZ", "is_st"])
    assert bool(frame.loc["000002.SZ", "is_suspended"])
    assert warehouse.history_query is not None
    assert warehouse.history_query.decision_at == DECISION_AT
    assert set(warehouse.history_query.indicator_ids) == {
        "close",
        "amount",
        "adj_factor",
    }


def test_feature_mart_loader_reads_materialized_cross_section() -> None:
    """Third-layer ETL writes fourth-layer features consumed by quant."""
    warehouse = FakeWarehouse()
    repository = MemoryAnalysisMartRepository()
    snapshot = QuantInputSnapshot(
        scope_version_id="scope-v1",
        universe_snapshot_id="universe-v1",
        decision_at=DECISION_AT,
        known_at=DECISION_AT,
        security_ids=("000001.SZ", "000002.SZ"),
        required_indicators=("net_profit_ttm", "pe_ttm"),
        optional_indicators=("roe_ttm", "audit_opinion"),
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
    assert loaded.loc["000001.SZ", "avg_amount_20d"] == 100_000_000
    assert loaded.loc["000001.SZ", "return_12m_ex_1m"] > 0
    assert bool(loaded.loc["000002.SZ", "is_st"])
    assert bool(loaded.loc["000002.SZ", "is_suspended"])


def test_feature_mart_etl_pipeline_binds_snapshot_before_quant_read() -> None:
    """Managed ETL returns a quant input bound to the fourth-layer feature set."""
    warehouse = FakeWarehouse()
    repository = MemoryAnalysisMartRepository()
    snapshot = QuantInputSnapshot(
        scope_version_id="scope-v1",
        universe_snapshot_id="universe-v1",
        decision_at=DECISION_AT,
        known_at=DECISION_AT,
        security_ids=("000001.SZ", "000002.SZ"),
        required_indicators=("net_profit_ttm", "pe_ttm"),
        optional_indicators=("roe_ttm", "audit_opinion"),
        market_window_start=datetime(2025, 1, 1, tzinfo=UTC),
        market_window_end=DECISION_AT,
    )
    pipeline = QuantFeatureMartETLPipeline(
        repository=repository,
        source_loader=build_cross_section_loader(warehouse),
    )

    result = pipeline.materialize(snapshot)
    loaded = build_feature_mart_cross_section_loader(repository)(
        result.input_snapshot
    )

    assert result.input_snapshot.feature_snapshot_id == (
        result.feature_snapshot.feature_snapshot_id
    )
    assert repository.get_feature_snapshot(result.feature_snapshot.feature_snapshot_id)
    assert loaded.loc["000001.SZ", "pe_ttm"] == 10.0


def _canonical(
    security_id: str,
    indicator_id: str,
    value: str,
) -> CanonicalValue:
    """Build one current canonical value."""
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
    """Build one current canonical text value."""
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
    """Build one active industry membership."""
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
    """Build close and amount historical facts."""
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
