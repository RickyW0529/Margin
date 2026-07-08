"""Quality screening between Tushare landing tables and the warehouse."""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel

from margin.data.requirements import QuantDataRequirementCatalog
from margin.data.tushare_source import (
    TushareLandingRecord,
    is_delisting_security_name,
    is_st_security_name,
)
from margin.news.models import ensure_utc


class SourceQualityDecision(BaseModel):
    """Immutable publication decision for one source landing row."""

    decision_id: str
    provider: str = "tushare"
    endpoint: str
    source_row_id: str
    decision: Literal["accepted", "quarantined", "rejected"]
    quality_score: Decimal
    issue_codes: tuple[str, ...]
    rule_version: str = "tushare-quality-v0.3.0"
    published_fact_count: int = 0
    checked_at: datetime

    model_config = {"frozen": True}


def select_current_non_st_securities(
    records: list[dict[str, Any]],
    *,
    as_of: datetime | date | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Filter stock-basic rows before persistence and report exclusion counts.

    Args:
        records: Raw ``stock_basic`` rows from Tushare.
        as_of: Optional reference date for listing-date filtering.

    Returns:
        A tuple of ``(accepted_rows, excluded_counts)`` where ``excluded_counts``
        breaks down exclusions by ``st``, ``not_listed``, and ``invalid_symbol``.
    """
    accepted: list[dict[str, Any]] = []
    excluded = {"st": 0, "not_listed": 0, "invalid_symbol": 0}
    as_of_date = _normalize_date(as_of)
    for record in records:
        symbol = str(record.get("ts_code") or "").strip().upper()
        if not symbol or "." not in symbol:
            excluded["invalid_symbol"] += 1
            continue
        if str(record.get("list_status") or "L").strip().upper() != "L":
            excluded["not_listed"] += 1
            continue
        list_date = _parse_yyyymmdd(record.get("list_date"))
        if as_of_date is not None and list_date is not None and list_date > as_of_date:
            excluded["not_listed"] += 1
            continue
        if is_st_security_name(str(record.get("name") or "")):
            excluded["st"] += 1
            continue
        if is_delisting_security_name(str(record.get("name") or "")):
            excluded["not_listed"] += 1
            continue
        accepted.append(record)
    return accepted, excluded


class TushareQualityScreen:
    """Apply deterministic row-level admission before warehouse publication."""

    _WINDOWED_ENDPOINTS = {
        "daily",
        "adj_factor",
        "suspend_d",
        "daily_basic",
        "moneyflow",
        "margin_detail",
        "pledge_stat",
        "index_daily",
        "index_weight",
        "limit_list_d",
    }
    _SYMBOL_ENDPOINTS = {
        "stock_basic",
        "namechange",
        "daily",
        "adj_factor",
        "suspend_d",
        "daily_basic",
        "moneyflow",
        "margin_detail",
        "income",
        "balancesheet",
        "cashflow",
        "fina_indicator",
        "fina_audit",
        "forecast",
        "express",
        "index_member",
        "pledge_stat",
        "index_weight",
        "limit_list_d",
    }

    def evaluate(
        self,
        record: TushareLandingRecord,
        *,
        window_start: datetime,
        window_end: datetime,
        eligible_symbols: set[str],
        checked_at: datetime | None = None,
    ) -> SourceQualityDecision:
        """Return accepted, quarantined, or rejected with stable issue codes.

        Args:
            record: The landing record to evaluate.
            window_start: The rolling-window start boundary.
            window_end: The rolling-window end boundary.
            eligible_symbols: The set of company-pool eligible symbols.
            checked_at: Optional override for the decision timestamp.

        Returns:
            A ``SourceQualityDecision`` with the admission verdict and score.
        """
        start = ensure_utc(window_start).date()
        end = ensure_utc(window_end).date()
        issues: list[str] = []
        endpoint = QuantDataRequirementCatalog.default().endpoint(
            "tushare",
            record.endpoint,
        )
        if any(
            record.raw_payload.get(field) in (None, "")
            for field in endpoint.natural_key_fields
        ):
            issues.append("missing_natural_key")
        if (
            record.endpoint in self._SYMBOL_ENDPOINTS
            and record.symbol not in eligible_symbols
        ):
            issues.append("symbol_not_in_company_pool")
        if (
            record.endpoint in self._WINDOWED_ENDPOINTS
            and record.business_date is not None
            and not start <= record.business_date <= end
        ):
            issues.append("outside_rolling_window")
        if (
            record.published_at is not None
            and record.published_at.date() > end
        ):
            issues.append("future_publication")

        reject_issues = {
            "missing_natural_key",
            "symbol_not_in_company_pool",
            "future_publication",
        }
        if reject_issues.intersection(issues):
            decision: Literal["accepted", "quarantined", "rejected"] = "rejected"
        elif issues:
            decision = "quarantined"
        else:
            decision = "accepted"
        score = max(Decimal("0"), Decimal("1") - Decimal("0.25") * len(issues))
        observed_at = ensure_utc(checked_at or record.fetched_at)
        digest = hashlib.sha256(
            (
                f"tushare|{record.endpoint}|{record.source_row_id}|"
                f"tushare-quality-v0.3.0"
            ).encode()
        ).hexdigest()
        return SourceQualityDecision(
            decision_id=f"sqd:{digest}",
            endpoint=record.endpoint,
            source_row_id=record.source_row_id,
            decision=decision,
            quality_score=score,
            issue_codes=tuple(issues),
            checked_at=observed_at,
        )


def _normalize_date(value: datetime | date | None) -> date | None:
    """Return a date boundary for as-of security-master filtering."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return ensure_utc(value).date()
    return value


def _parse_yyyymmdd(value: Any) -> date | None:
    """Parse Tushare date strings without rejecting unknown legacy blanks."""
    normalized = str(value or "").strip()
    if not normalized:
        return None
    try:
        return datetime.strptime(normalized[:8], "%Y%m%d").date()
    except ValueError:
        return None
