"""Endpoint and partition planning for the v1 20-year backfill."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from margin.agent_runtime.context_store import stable_json_hash
from margin.data.backfill.campaign import BackfillCampaign

ALWAYS_INCLUDED_PROVIDERS = {
    "exchange",
    "provider",
    "public",
    "web",
    "document",
    "local",
}


class PartitionStatus(StrEnum):
    """PartitionStatus.."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    BLOCKED = "blocked"


class BackfillEndpoint(BaseModel):
    """BackfillEndpoint.."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_name: str
    endpoint_name: str
    data_category: str
    partition_strategy: Literal["snapshot", "monthly", "quarterly", "yearly"]
    required: bool = True

    @property
    def qualified_name(self) -> str:
        """Qualified name.

        Returns:
            str: .
        """
        return f"{self.provider_name}.{self.endpoint_name}"


class BackfillEndpointPlan(BaseModel):
    """BackfillEndpointPlan.."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    campaign_id: str
    plan_version: str = "backfill-endpoint-plan-v1"
    coverage_start: date
    coverage_end: date
    providers: tuple[str, ...]
    endpoints: tuple[BackfillEndpoint, ...]
    payload_hash: str


class BackfillPartition(BaseModel):
    """BackfillPartition.."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    partition_id: str
    campaign_id: str
    provider_name: str
    endpoint_name: str
    partition_start: date
    partition_end: date
    params_hash: str
    status: PartitionStatus = PartitionStatus.PENDING
    retryable: bool = True
    attempt_count: int = Field(default=0, ge=0)


class BackfillPlanner:
    """BackfillPlanner.."""

    def plan_endpoints(self, campaign: BackfillCampaign) -> BackfillEndpointPlan:
        """Plan endpoints.

        Args:
            campaign: BackfillCampaign: .

        Returns:
            BackfillEndpointPlan: .
        """
        endpoints = tuple(
            endpoint
            for endpoint in _endpoint_catalog()
            if endpoint.provider_name in campaign.providers
            or endpoint.provider_name in ALWAYS_INCLUDED_PROVIDERS
        )
        payload = {
            "campaign_id": campaign.campaign_id,
            "coverage_start": campaign.start_date.isoformat(),
            "coverage_end": campaign.end_date.isoformat(),
            "providers": campaign.providers,
            "endpoints": [endpoint.model_dump() for endpoint in endpoints],
        }
        return BackfillEndpointPlan(
            campaign_id=campaign.campaign_id,
            coverage_start=campaign.start_date,
            coverage_end=campaign.end_date,
            providers=campaign.providers,
            endpoints=endpoints,
            payload_hash=stable_json_hash(payload),
        )

    def plan_partitions(
        self,
        campaign: BackfillCampaign,
        endpoint_plan: BackfillEndpointPlan,
    ) -> tuple[BackfillPartition, ...]:
        """Plan partitions.

        Args:
            campaign: BackfillCampaign: .
            endpoint_plan: BackfillEndpointPlan: .

        Returns:
            tuple[BackfillPartition, ...]: .
        """
        partitions: list[BackfillPartition] = []
        for endpoint in endpoint_plan.endpoints:
            for start, end in _partition_windows(
                campaign.start_date,
                campaign.end_date,
                endpoint.partition_strategy,
            ):
                params = {
                    "campaign_id": campaign.campaign_id,
                    "provider_name": endpoint.provider_name,
                    "endpoint_name": endpoint.endpoint_name,
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                    "strategy": endpoint.partition_strategy,
                }
                params_hash = stable_json_hash(params)
                partitions.append(
                    BackfillPartition(
                        partition_id=f"bfp_{params_hash.removeprefix('sha256:')[:24]}",
                        campaign_id=campaign.campaign_id,
                        provider_name=endpoint.provider_name,
                        endpoint_name=endpoint.endpoint_name,
                        partition_start=start,
                        partition_end=end,
                        params_hash=params_hash,
                    )
                )
        return tuple(partitions)

    def resume_after_failure(
        self,
        partitions: Iterable[BackfillPartition],
    ) -> tuple[BackfillPartition, ...]:
        """Resume after failure.

        Args:
            partitions: Iterable[BackfillPartition]: .

        Returns:
            tuple[BackfillPartition, ...]: .
        """
        return tuple(
            partition
            for partition in partitions
            if partition.status in {PartitionStatus.FAILED, PartitionStatus.PARTIAL}
            and partition.retryable
        )


def _endpoint_catalog() -> tuple[BackfillEndpoint, ...]:
    """Endpoint catalog.

    Returns:
        tuple[BackfillEndpoint, ...]: .
    """

    def ep(
        provider_name: str,
        endpoint_name: str,
        data_category: str,
        partition_strategy: Literal["snapshot", "monthly", "quarterly", "yearly"],
    ) -> BackfillEndpoint:
        """Ep.

        Args:
            provider_name: str: .
            endpoint_name: str: .
            data_category: str: .
            partition_strategy: Literal['snapshot', 'monthly', 'quarterly', 'yearly']: .

        Returns:
            BackfillEndpoint: .
        """
        return BackfillEndpoint(
            provider_name=provider_name,
            endpoint_name=endpoint_name,
            data_category=data_category,
            partition_strategy=partition_strategy,
        )

    return (
        ep("tushare", "stock_basic", "base", "snapshot"),
        ep("tushare", "namechange", "base", "yearly"),
        ep("tushare", "trade_cal", "base", "yearly"),
        ep("akshare", "stock_info_a_code_name", "base", "snapshot"),
        ep("tushare", "daily", "market_quote", "monthly"),
        ep("tushare", "weekly", "market_quote", "monthly"),
        ep("tushare", "monthly", "market_quote", "yearly"),
        ep("tushare", "adj_factor", "market_quote", "monthly"),
        ep("tushare", "stk_factor", "market_quote", "monthly"),
        ep("akshare", "stock_zh_a_hist", "market_quote", "monthly"),
        ep("tushare", "daily_basic", "valuation", "monthly"),
        ep("tushare", "moneyflow", "moneyflow", "monthly"),
        ep("tushare", "margin", "margin", "monthly"),
        ep("tushare", "margin_detail", "margin", "monthly"),
        ep("tushare", "income", "financial", "quarterly"),
        ep("tushare", "balancesheet", "financial", "quarterly"),
        ep("tushare", "cashflow", "financial", "quarterly"),
        ep("tushare", "fina_indicator", "financial", "quarterly"),
        ep("tushare", "fina_audit", "financial", "yearly"),
        ep("tushare", "forecast", "financial_event", "quarterly"),
        ep("tushare", "express", "financial_event", "quarterly"),
        ep("tushare", "disclosure_date", "financial_event", "quarterly"),
        ep("tushare", "dividend", "corporate_action", "yearly"),
        ep("tushare", "suspend_d", "trade_constraint", "monthly"),
        ep("tushare", "limit_list_d", "trade_constraint", "monthly"),
        ep("tushare", "stk_limit", "trade_constraint", "monthly"),
        ep("tushare", "index_basic", "benchmark", "snapshot"),
        ep("tushare", "index_weight", "benchmark", "monthly"),
        ep("provider", "industry_classification", "classification", "yearly"),
        ep("local", "stock_pool_snapshots", "stock_pool", "monthly"),
        ep("exchange", "filings", "document", "monthly"),
        ep("provider", "disclosures", "document", "monthly"),
        ep("public", "news", "news", "monthly"),
        ep("web", "search_snippets", "news", "monthly"),
        ep("document", "snapshots", "document", "monthly"),
    )


def _partition_windows(
    start: date,
    end: date,
    strategy: Literal["snapshot", "monthly", "quarterly", "yearly"],
) -> tuple[tuple[date, date], ...]:
    """Partition windows.

    Args:
        start: date: .
        end: date: .
        strategy: Literal['snapshot', 'monthly', 'quarterly', 'yearly']: .

    Returns:
        tuple[tuple[date, date], ...]: .
    """
    if strategy == "snapshot":
        return ((start, end),)
    if strategy == "monthly":
        return tuple(_month_windows(start, end))
    if strategy == "quarterly":
        return tuple(_quarter_windows(start, end))
    return tuple(_year_windows(start, end))


def _month_windows(start: date, end: date) -> Iterable[tuple[date, date]]:
    """Month windows.

    Args:
        start: date: .
        end: date: .

    Yields:
        Any: .
    """
    current = date(start.year, start.month, 1)
    while current <= end:
        next_month = _add_months(current, 1)
        window_start = max(start, current)
        window_end = min(end, next_month - timedelta(days=1))
        yield window_start, window_end
        current = next_month


def _quarter_windows(start: date, end: date) -> Iterable[tuple[date, date]]:
    """Quarter windows.

    Args:
        start: date: .
        end: date: .

    Yields:
        Any: .
    """
    first_quarter_month = ((start.month - 1) // 3) * 3 + 1
    current = date(start.year, first_quarter_month, 1)
    while current <= end:
        next_quarter = _add_months(current, 3)
        window_start = max(start, current)
        window_end = min(end, next_quarter - timedelta(days=1))
        yield window_start, window_end
        current = next_quarter


def _year_windows(start: date, end: date) -> Iterable[tuple[date, date]]:
    """Year windows.

    Args:
        start: date: .
        end: date: .

    Yields:
        Any: .
    """
    current = date(start.year, 1, 1)
    while current <= end:
        next_year = date(current.year + 1, 1, 1)
        window_start = max(start, current)
        window_end = min(end, next_year - timedelta(days=1))
        yield window_start, window_end
        current = next_year


def _add_months(value: date, months: int) -> date:
    """Add months.

    Args:
        value: date: .
        months: int: .

    Returns:
        date: .
    """
    month_index = value.year * 12 + value.month - 1 + months
    year = month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)
