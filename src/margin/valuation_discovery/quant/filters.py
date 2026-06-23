"""Hard filters applied before factor scoring."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pandas as pd

from margin.valuation_discovery.models import DataStatus
from margin.valuation_discovery.quant.config import QuantConfig
from margin.valuation_discovery.quant.models import (
    FilterReason,
    HardFilterResult,
    SecurityFilterResult,
)


class HardFilterEngine:
    """Apply configurable hard filters while preserving structured reasons."""

    def __init__(self, config: QuantConfig) -> None:
        """init  ."""
        self._config = config

    def apply(self, frame: pd.DataFrame) -> HardFilterResult:
        """Apply hard filters to a quant cross-section."""
        results: dict[str, SecurityFilterResult] = {}
        for security_id, row in frame.iterrows():
            row_security_id = str(row.get("security_id", security_id))
            reasons = tuple(self._reasons_for(row))
            has_blocker = any(reason.severity == "blocker" for reason in reasons)
            data_status = (
                DataStatus.INSUFFICIENT
                if any(reason.code == "missing_critical_financial" for reason in reasons)
                else DataStatus.OK
            )
            results[row_security_id] = SecurityFilterResult(
                security_id=row_security_id,
                allowed_for_scoring=not has_blocker,
                data_status=data_status,
                reasons=reasons,
            )
        return HardFilterResult(by_security=results)

    def _reasons_for(self, row: pd.Series) -> list[FilterReason]:
        """reasons for."""
        reasons: list[FilterReason] = []
        if bool(row.get("is_st", False)):
            reasons.append(
                FilterReason(
                    code="st_stock",
                    severity="blocker",
                    message="ST or *ST stock is excluded before scoring.",
                    observed=True,
                    threshold=False,
                )
            )
        if bool(row.get("is_suspended", False)):
            reasons.append(
                FilterReason(
                    code="suspended",
                    severity="blocker",
                    message="Suspended stock is excluded before scoring.",
                    observed=True,
                    threshold=False,
                )
            )
        reasons.extend(self._listing_reasons(row))
        reasons.extend(self._liquidity_reasons(row))
        reasons.extend(self._financial_completeness_reasons(row))
        reasons.extend(self._profitability_reasons(row))
        reasons.extend(self._balance_sheet_reasons(row))
        reasons.extend(self._cashflow_reasons(row))
        reasons.extend(self._audit_reasons(row))
        return reasons

    def _listing_reasons(self, row: pd.Series) -> list[FilterReason]:
        """listing reasons."""
        listing_date = row.get("listing_date")
        decision_at = _coerce_datetime(row.get("decision_at")) or datetime.now(UTC)
        listed_at = _coerce_datetime(listing_date)
        if listed_at is None:
            return []
        listed_months = (
            (decision_at.year - listed_at.year) * 12
            + decision_at.month
            - listed_at.month
        )
        if listed_months < self._config.min_listing_months:
            return [
                FilterReason(
                    code="new_listing",
                    severity="blocker",
                    message="Listed history is shorter than configured threshold.",
                    observed=listed_months,
                    threshold=self._config.min_listing_months,
                    indicator_id="listing_date",
                )
            ]
        return []

    def _liquidity_reasons(self, row: pd.Series) -> list[FilterReason]:
        """liquidity reasons."""
        observed = _number_or_none(row.get("avg_amount_20d"))
        if observed is not None and observed < self._config.min_avg_amount_20d:
            return [
                FilterReason(
                    code="low_liquidity",
                    severity="blocker",
                    message="Average 20-day amount is below configured threshold.",
                    observed=observed,
                    threshold=self._config.min_avg_amount_20d,
                    indicator_id="avg_amount_20d",
                )
            ]
        return []

    def _financial_completeness_reasons(self, row: pd.Series) -> list[FilterReason]:
        """financial completeness reasons."""
        missing = [
            field
            for field in self._config.critical_financial_fields
            if _is_missing(row.get(field))
        ]
        return [
            FilterReason(
                code="missing_critical_financial",
                severity="blocker",
                message="Critical financial field is missing.",
                observed=None,
                threshold="required",
                indicator_id=field,
            )
            for field in missing
        ]

    def _profitability_reasons(self, row: pd.Series) -> list[FilterReason]:
        """profitability reasons."""
        y1 = _number_or_none(row.get("net_profit_y1"))
        y2 = _number_or_none(row.get("net_profit_y2"))
        if y1 is not None and y2 is not None and y1 < 0 and y2 < 0:
            return [
                FilterReason(
                    code="two_year_losses",
                    severity="blocker",
                    message="Net profit is negative for two consecutive years.",
                    observed=(y1, y2),
                    threshold=">= 0 in at least one year",
                    indicator_id="net_profit",
                )
            ]
        return []

    def _balance_sheet_reasons(self, row: pd.Series) -> list[FilterReason]:
        """balance sheet reasons."""
        reasons: list[FilterReason] = []
        industry_family = str(row.get("industry_family") or "").lower()
        liability_threshold = (
            self._config.financial_liability_ratio_max
            if industry_family in self._config.financial_industry_families
            else self._config.liability_ratio_max
        )
        liability_ratio = _number_or_none(row.get("liability_ratio"))
        if liability_ratio is not None and liability_ratio > liability_threshold:
            reasons.append(
                FilterReason(
                    code="high_liability_ratio",
                    severity="blocker",
                    message="Liability ratio exceeds configured threshold.",
                    observed=liability_ratio,
                    threshold=liability_threshold,
                    indicator_id="liability_ratio",
                )
            )
        goodwill_to_equity = _number_or_none(row.get("goodwill_to_equity"))
        if (
            goodwill_to_equity is not None
            and goodwill_to_equity > self._config.goodwill_to_equity_risk
        ):
            reasons.append(
                FilterReason(
                    code="goodwill_risk",
                    severity="risk",
                    message="Goodwill to equity exceeds risk threshold.",
                    observed=goodwill_to_equity,
                    threshold=self._config.goodwill_to_equity_risk,
                    indicator_id="goodwill_to_equity",
                )
            )
        return reasons

    def _cashflow_reasons(self, row: pd.Series) -> list[FilterReason]:
        """cashflow reasons."""
        observed = _number_or_none(row.get("ocf_to_net_profit"))
        if observed is not None and observed < self._config.min_ocf_to_net_profit:
            return [
                FilterReason(
                    code="weak_cashflow_quality",
                    severity="risk",
                    message="Operating cashflow is significantly below net profit.",
                    observed=observed,
                    threshold=self._config.min_ocf_to_net_profit,
                    indicator_id="ocf_to_net_profit",
                )
            ]
        return []

    def _audit_reasons(self, row: pd.Series) -> list[FilterReason]:
        """audit reasons."""
        opinion = str(row.get("audit_opinion") or "").lower()
        if opinion and opinion in self._config.abnormal_audit_opinions:
            return [
                FilterReason(
                    code="abnormal_audit_opinion",
                    severity="review",
                    message="Audit opinion requires review.",
                    observed=opinion,
                    threshold="standard_unqualified",
                    indicator_id="audit_opinion",
                )
            ]
        return []


def _number_or_none(value: Any) -> float | None:
    """number or none."""
    if _is_missing(value):
        return None
    return float(value)


def _is_missing(value: Any) -> bool:
    """is missing."""
    return value is None or bool(pd.isna(value))


def _coerce_datetime(value: Any) -> datetime | None:
    """coerce datetime."""
    if _is_missing(value):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    return None
