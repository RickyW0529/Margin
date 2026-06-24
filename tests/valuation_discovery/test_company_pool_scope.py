"""Company-pool to quant-scope integration tests."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from margin.data.company_pool import build_company_pool_snapshot
from margin.strategy.models import IndicatorSelectionMode
from margin.valuation_discovery.quant_adapter import SQLAlchemyScopeBindingProvider


class _Strategy:
    def get_research_scope(self, _version_id: str):
        return SimpleNamespace(
            version_id="scope-v1",
            quant_feature_set_version_id="features-v1",
            quant_strategy_version_id="strategy-v1",
            indicator_view_version_id="view-v1",
            universe_version_id="universe-v1",
            canonical_rule_version="canonical-v1",
        )

    def get_quant_feature_set(self, _version_id: str):
        return SimpleNamespace(
            version_id="features-v1",
            required_indicators=("net_profit_ttm", "pe_ttm"),
            optional_indicators=("roe_ttm",),
            history_days=500,
        )

    def get_quant_strategy(self, _version_id: str):
        return SimpleNamespace(
            version_id="strategy-v1",
            strategy_family="default",
            factor_weights={"value": 1.0},
            thresholds={"default_universe": "ALL_A"},
            calibration_report_id="calibrated",
        )

    def get_indicator_view(self, _version_id: str):
        return SimpleNamespace(
            version_id="view-v1",
            mode=IndicatorSelectionMode.ALL,
            included_indicators=(),
            excluded_indicators=(),
        )

    def get_universe_definition(self, _version_id: str):
        return SimpleNamespace(
            version_id="universe-v1",
            universe_code="ALL_A",
            member_security_ids=("stale-static-member",),
        )


class _CompanyPool:
    def latest(self):
        now = datetime(2026, 6, 23, tzinfo=UTC)
        return build_company_pool_snapshot(
            [
                {
                    "security_id": "000001.SZ",
                    "name": "平安银行",
                    "exchange": "SZ",
                }
            ],
            source_run_id="run-1",
            business_at=now,
            known_at=now,
        )


def test_all_a_scope_uses_latest_non_st_company_pool_snapshot() -> None:
    """Quant snapshots consume the frozen company-pool view, not stale config members."""
    provider = SQLAlchemyScopeBindingProvider(
        _Strategy(),
        company_pool_repository=_CompanyPool(),
    )

    binding = provider.get_scope_binding("scope-v1")

    assert binding.universe_snapshot.security_ids == ("000001.SZ",)
    assert binding.universe_snapshot.snapshot_id.startswith("cps_")
    assert binding.universe_snapshot.universe_code == "ALL_A_NON_ST"
    assert (
        binding.quant_feature_set.metadata["quant_strategy"][
            "quant_strategy_version_id"
        ]
        == "strategy-v1"
    )
