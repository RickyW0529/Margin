"""Configuration for v0.2 quant screening."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class QuantConfig(BaseModel):
    """Configurable thresholds for hard filters and scoring."""

    model_config = ConfigDict(frozen=True)

    min_listing_months: int = 12
    min_avg_amount_20d: float = 50_000_000
    liability_ratio_max: float = 0.85
    financial_liability_ratio_max: float = 0.95
    goodwill_to_equity_risk: float = 0.40
    min_ocf_to_net_profit: float = 0.50
    critical_financial_fields: tuple[str, ...] = ("net_profit_ttm",)
    financial_industry_families: tuple[str, ...] = ("bank", "insurance", "brokerage", "financial")
    abnormal_audit_opinions: tuple[str, ...] = (
        "qualified",
        "adverse",
        "disclaimer",
        "unable_to_opine",
    )
