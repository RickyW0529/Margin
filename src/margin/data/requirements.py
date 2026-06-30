"""Quant-driven provider endpoint admission catalog.

The catalog is intentionally explicit: provider capability does not imply
collection. An endpoint is admitted only when an active quant, hard-filter,
universe, PIT/adjustment, or benchmark requirement consumes it.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, Field


class QuantDataRequirement(BaseModel):
    """One versioned data requirement owned by a deterministic consumer."""

    code: str
    consumer: str
    warehouse_fields: tuple[str, ...]
    minimum_history_days: int = Field(default=0, ge=0)
    active: bool = True
    description: str

    model_config = {"frozen": True}


class ProviderEndpointRequirement(BaseModel):
    """Provider endpoint candidate and its quant admission decision."""

    provider: str
    api_name: str
    domain: str
    admission: Literal["enabled", "out_of_scope"]
    quant_requirement_codes: tuple[str, ...] = ()
    partition_by: str
    natural_key_fields: tuple[str, ...]
    pit_fields: tuple[str, ...]
    description: str

    model_config = {"frozen": True}


class QuantDataRequirementCatalog:
    """Resolve provider endpoints from active quant data requirements."""

    def __init__(
        self,
        *,
        requirements: Iterable[QuantDataRequirement],
        endpoints: Iterable[ProviderEndpointRequirement],
    ) -> None:
        """Initialize and validate requirement links.

        Args:
            requirements: Quant data requirements keyed by code.
            endpoints: Provider endpoint candidates with admission decisions.

        Raises:
            ValueError: If an endpoint references an unknown requirement or an
                enabled endpoint has no quant requirement.
        """
        self._requirements = {item.code: item for item in requirements}
        self._endpoints = {
            (item.provider.lower(), item.api_name.lower()): item
            for item in endpoints
        }
        for endpoint in self._endpoints.values():
            missing = [
                code
                for code in endpoint.quant_requirement_codes
                if code not in self._requirements
            ]
            if missing:
                raise ValueError(
                    f"endpoint {endpoint.provider}/{endpoint.api_name} "
                    f"references unknown requirement {missing[0]}"
                )
            if endpoint.admission == "enabled" and not endpoint.quant_requirement_codes:
                raise ValueError(
                    f"enabled endpoint has no quant requirement: "
                    f"{endpoint.provider}/{endpoint.api_name}"
                )

    def enabled_endpoints(
        self,
        provider: str,
    ) -> tuple[ProviderEndpointRequirement, ...]:
        """Return endpoints admitted by at least one active requirement.

        Args:
            provider: The provider name to filter by.

        Returns:
            Enabled endpoints for the provider, sorted by provider and API name.
        """
        normalized = provider.strip().lower()
        return tuple(
            endpoint
            for endpoint in sorted(
                self._endpoints.values(),
                key=lambda item: (item.provider, item.api_name),
            )
            if endpoint.provider.lower() == normalized
            and endpoint.admission == "enabled"
            and all(
                self._requirements[code].active
                for code in endpoint.quant_requirement_codes
            )
        )

    def requirements(self) -> tuple[QuantDataRequirement, ...]:
        """Return all cataloged quant requirements in stable order.

        Returns:
            All requirements sorted by code.
        """
        return tuple(
            self._requirements[code]
            for code in sorted(self._requirements)
        )

    def endpoints(
        self,
        provider: str | None = None,
    ) -> tuple[ProviderEndpointRequirement, ...]:
        """Return all endpoint decisions, optionally scoped to one provider.

        Args:
            provider: Optional provider name filter.

        Returns:
            Endpoint decisions sorted by provider and API name.
        """
        normalized = provider.strip().lower() if provider else None
        return tuple(
            endpoint
            for endpoint in sorted(
                self._endpoints.values(),
                key=lambda item: (item.provider, item.api_name),
            )
            if normalized is None or endpoint.provider.lower() == normalized
        )

    def endpoint(
        self,
        provider: str,
        api_name: str,
    ) -> ProviderEndpointRequirement:
        """Return one endpoint catalog entry.

        Args:
            provider: The provider name.
            api_name: The API name.

        Returns:
            The matching endpoint requirement.
        """
        return self._endpoints[(provider.strip().lower(), api_name.strip().lower())]

    def requirements_for_endpoint(
        self,
        *,
        provider: str,
        api_name: str,
    ) -> tuple[QuantDataRequirement, ...]:
        """Return quant requirements that admit one endpoint.

        Args:
            provider: The provider name.
            api_name: The API name.

        Returns:
            Quant requirements linked to the endpoint.
        """
        endpoint = self.endpoint(provider, api_name)
        return tuple(
            self._requirements[code]
            for code in endpoint.quant_requirement_codes
        )

    @classmethod
    def default(cls) -> QuantDataRequirementCatalog:
        """Build the v0.3 default quant requirement closure.

        Returns:
            A catalog with 15 quant requirements and 16 enabled Tushare
            endpoints plus 7 out-of-scope cataloged endpoints.
        """
        requirements = (
            _requirement(
                "security_master",
                "ALL_A_NON_ST + HardFilterEngine",
                ("symbol", "name", "exchange", "listing_date", "listing_status"),
                "Build the A-share universe and listing-age filter.",
            ),
            _requirement(
                "st_status",
                "ALL_A_NON_ST",
                ("security_status", "name_history", "is_st"),
                "Exclude ST, *ST, delisting-transition, and delisted securities PIT-safely.",
            ),
            _requirement(
                "trading_calendar",
                "freshness + suspension filter",
                ("trade_date", "is_open", "previous_open_date"),
                "Determine expected market dates and distinguish holidays from suspension.",
            ),
            _requirement(
                "market_history",
                "liquidity + momentum + risk factors",
                ("close", "amount"),
                "Calculate liquidity, returns, volatility, drawdown, and trend.",
                history=760,
            ),
            _requirement(
                "adjustment_history",
                "PIT adjusted market history",
                ("adj_factor",),
                "Build no-lookahead adjusted prices.",
                history=760,
            ),
            _requirement(
                "suspension_status",
                "HardFilterEngine",
                ("is_suspended", "suspend_type"),
                "Exclude suspended securities without inferring solely from missing bars.",
            ),
            _requirement(
                "valuation_snapshot",
                "ValueFactorCalculator",
                (
                    "pe_ttm",
                    "pb",
                    "ps",
                    "dividend_yield",
                    "market_cap",
                    "turnover_rate",
                ),
                "Calculate value factors and market-cap context.",
            ),
            _requirement(
                "income_fundamentals",
                "quality + growth + profitability filters",
                (
                    "net_profit_ttm",
                    "net_profit_y1",
                    "net_profit_y2",
                    "revenue_yoy",
                    "profit_yoy",
                    "revenue_cagr_3y",
                    "profit_cagr_3y",
                    "margin_trend",
                ),
                "Supply profitability and growth features.",
                history=1095,
            ),
            _requirement(
                "balance_sheet_fundamentals",
                "quality + balance-sheet risk filters",
                (
                    "liability_ratio",
                    "goodwill_to_equity",
                    "receivable_risk",
                    "inventory_risk",
                ),
                "Supply leverage and asset-quality risk features.",
                history=1095,
            ),
            _requirement(
                "cashflow_fundamentals",
                "quality + cashflow hard filter",
                ("ocf_to_net_profit",),
                "Measure earnings cash conversion.",
                history=1095,
            ),
            _requirement(
                "financial_ratios",
                "QualityFactorCalculator + GrowthFactorCalculator",
                (
                    "roe_ttm",
                    "roic_ttm",
                    "gross_margin_ttm",
                    "net_margin_ttm",
                    "interest_coverage",
                    "roe_trend",
                ),
                "Supply standardized quality ratios.",
                history=1095,
            ),
            _requirement(
                "audit_opinion",
                "HardFilterEngine",
                ("audit_opinion",),
                "Flag qualified, adverse, disclaimer, and unable-to-opine reports.",
                history=1095,
            ),
            _requirement(
                "industry_classification",
                "industry-neutral factor normalization",
                ("industry_code", "industry_name", "industry_level"),
                "Provide PIT industry membership for peer-relative factor scoring.",
                history=760,
            ),
            _requirement(
                "pledge_risk",
                "RiskFactorCalculator",
                ("pledge_ratio",),
                "Measure aggregate shareholder pledge risk without collecting pledge details.",
                history=760,
            ),
            _requirement(
                "benchmark_history",
                "relative momentum + universe benchmark",
                ("index_close", "index_return", "index_weight"),
                "Calculate index-relative momentum and materialize benchmark universes.",
                history=760,
            ),
        )
        links: dict[str, tuple[str, ...]] = {
            "stock_basic": ("security_master",),
            "namechange": ("st_status",),
            "trade_cal": ("trading_calendar",),
            "daily": ("market_history",),
            "adj_factor": ("adjustment_history",),
            "suspend_d": ("suspension_status",),
            "daily_basic": ("valuation_snapshot",),
            "income": ("income_fundamentals",),
            "balancesheet": ("balance_sheet_fundamentals",),
            "cashflow": ("cashflow_fundamentals",),
            "fina_indicator": ("financial_ratios",),
            "fina_audit": ("audit_opinion",),
            "index_classify": ("industry_classification",),
            "index_member": ("industry_classification",),
            "pledge_stat": ("pledge_risk",),
            "index_daily": ("benchmark_history",),
            "index_weight": ("benchmark_history",),
        }
        endpoints = [
            ProviderEndpointRequirement(
                provider="tushare",
                api_name=api_name,
                domain=_domain_for(api_name),
                admission="enabled",
                quant_requirement_codes=requirement_codes,
                partition_by=_partition_for(api_name),
                natural_key_fields=_natural_key_for(api_name),
                pit_fields=_pit_fields_for(api_name),
                description=f"Tushare {api_name} admitted by quant requirements.",
            )
            for api_name, requirement_codes in links.items()
        ]
        endpoints.extend(
            ProviderEndpointRequirement(
                provider="tushare",
                api_name=api_name,
                domain=domain,
                admission="out_of_scope",
                partition_by="none",
                natural_key_fields=(),
                pit_fields=(),
                description="Cataloged but not collected because no active quant consumer exists.",
            )
            for api_name, domain in (
                ("top_list", "market_event"),
                ("top_inst", "market_event"),
                ("block_trade", "market_event"),
                ("margin", "financing"),
                ("pledge_detail", "shareholder"),
                ("stk_holdernumber", "shareholder"),
                ("concept", "classification"),
            )
        )
        return cls(requirements=requirements, endpoints=endpoints)


def _requirement(
    code: str,
    consumer: str,
    warehouse_fields: tuple[str, ...],
    description: str,
    *,
    history: int = 0,
) -> QuantDataRequirement:
    """Build one active default requirement."""
    return QuantDataRequirement(
        code=code,
        consumer=consumer,
        warehouse_fields=warehouse_fields,
        minimum_history_days=history,
        description=description,
    )


def _domain_for(api_name: str) -> str:
    """Return the warehouse domain for a Tushare API."""
    if api_name in {"stock_basic", "namechange"}:
        return "security"
    if api_name in {"trade_cal", "daily", "adj_factor", "suspend_d"}:
        return "market"
    if api_name == "daily_basic":
        return "valuation"
    if api_name in {
        "income",
        "balancesheet",
        "cashflow",
        "fina_indicator",
        "fina_audit",
    }:
        return "financial"
    if api_name in {"index_classify", "index_member"}:
        return "industry"
    if api_name == "pledge_stat":
        return "shareholder_risk"
    return "benchmark"


def _partition_for(api_name: str) -> str:
    """Return the bounded partition strategy for an endpoint."""
    if api_name in {"daily", "adj_factor", "daily_basic", "index_daily"}:
        return "trade_date"
    if api_name in {
        "income",
        "balancesheet",
        "cashflow",
        "fina_indicator",
        "fina_audit",
    }:
        return "announcement_month"
    if api_name == "index_member":
        return "membership_start_month"
    if api_name == "pledge_stat":
        return "end_date_month"
    if api_name == "index_weight":
        return "index_code_month"
    return "snapshot"


def _natural_key_for(api_name: str) -> tuple[str, ...]:
    """Return stable source natural-key fields."""
    if api_name == "trade_cal":
        return ("exchange", "cal_date")
    if api_name in {"daily", "adj_factor", "daily_basic", "index_daily"}:
        return ("ts_code", "trade_date")
    if api_name == "suspend_d":
        return ("ts_code", "trade_date", "suspend_type")
    if api_name in {"income", "balancesheet", "cashflow"}:
        return ("ts_code", "end_date", "report_type", "ann_date")
    if api_name == "fina_indicator":
        return ("ts_code", "end_date", "ann_date")
    if api_name == "fina_audit":
        return ("ts_code", "end_date", "ann_date")
    if api_name == "index_classify":
        return ("index_code", "level", "src")
    if api_name == "index_member":
        return ("index_code", "con_code", "in_date")
    if api_name == "pledge_stat":
        return ("ts_code", "end_date")
    if api_name == "namechange":
        return ("ts_code", "start_date", "end_date", "name")
    if api_name == "index_weight":
        return ("index_code", "con_code", "trade_date")
    return ("ts_code",)


def _pit_fields_for(api_name: str) -> tuple[str, ...]:
    """Return provider fields used to derive PIT timestamps."""
    if api_name in {"daily", "adj_factor", "daily_basic", "index_daily", "index_weight"}:
        return ("trade_date",)
    if api_name in {
        "income",
        "balancesheet",
        "cashflow",
        "fina_indicator",
        "fina_audit",
    }:
        return ("ann_date", "f_ann_date", "end_date")
    if api_name == "index_member":
        return ("in_date", "out_date")
    if api_name == "pledge_stat":
        return ("end_date",)
    if api_name == "namechange":
        return ("start_date", "end_date", "ann_date")
    return ()
