"""Point-in-time corporate action adjustment helpers."""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from margin.news.models import ensure_utc


class PriceBar(BaseModel):
    """Raw daily close used for as-of price adjustment."""

    security_id: str
    trade_date: date
    close: Decimal

    model_config = {"frozen": True}


class CorporateAction(BaseModel):
    """Corporate action with point-in-time availability."""

    security_id: str
    action_type: str
    ex_date: date | None = None
    cash_amount: Decimal | None = None
    share_ratio: Decimal | None = None
    available_at: datetime
    action_id: str | None = None

    model_config = {"frozen": True}

    @field_validator("available_at")
    @classmethod
    def normalize_available_at(cls, value: datetime) -> datetime:
        """Normalize availability timestamp to UTC."""
        return ensure_utc(value)

    @property
    def stable_id(self) -> str:
        """Return an action identifier stable enough for adjustment hashes."""
        if self.action_id:
            return self.action_id
        payload = (
            f"{self.security_id}|{self.action_type}|{self.ex_date}|"
            f"{self.cash_amount}|{self.share_ratio}|{self.available_at.isoformat()}"
        )
        return "ca_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class AdjustedPricePoint(BaseModel):
    """As-of adjusted price value."""

    security_id: str
    trade_date: date
    close: Decimal
    adj_close: Decimal
    adjustment_factor: Decimal
    policy_version: str
    input_action_ids: tuple[str, ...] = Field(default_factory=tuple)

    model_config = {"frozen": True}


class CorporateActionAdjuster:
    """Build PIT-safe adjusted prices from raw prices and available actions."""

    def __init__(self, *, policy_version: str = "adjust-v0.2.0") -> None:
        """Initialize the adjuster.

        Args:
            policy_version: Version tag stamped onto every adjusted price point.
        """
        self.policy_version = policy_version

    def build_as_of(
        self,
        prices: list[PriceBar],
        actions: list[CorporateAction],
        *,
        decision_at: datetime,
    ) -> tuple[AdjustedPricePoint, ...]:
        """Return adjusted price series using only actions available at decision time.

        Args:
            prices: Raw daily price bars sorted by trade date.
            actions: Corporate actions with point-in-time availability.
            decision_at: The point in time at which the adjustment is computed.

        Returns:
            A tuple of ``AdjustedPricePoint`` values, one per input price bar,
            each carrying the cumulative adjustment factor and input action IDs.
        """
        normalized_decision_at = ensure_utc(decision_at)
        available_actions = tuple(
            action for action in actions if action.available_at <= normalized_decision_at
        )
        points: list[AdjustedPricePoint] = []
        for price in sorted(prices, key=lambda item: item.trade_date):
            applicable = tuple(
                action
                for action in available_actions
                if action.security_id == price.security_id
                and action.ex_date is not None
                and action.ex_date <= price.trade_date
            )
            factor = Decimal("1")
            for action in applicable:
                factor *= _factor_for_action(price.close, action)
            points.append(
                AdjustedPricePoint(
                    security_id=price.security_id,
                    trade_date=price.trade_date,
                    close=price.close,
                    adj_close=(price.close * factor).quantize(Decimal("0.0000000001")),
                    adjustment_factor=factor.quantize(Decimal("0.0000000001")),
                    policy_version=self.policy_version,
                    input_action_ids=tuple(action.stable_id for action in applicable),
                )
            )
        return tuple(points)


def _factor_for_action(close: Decimal, action: CorporateAction) -> Decimal:
    """Return the cumulative adjustment factor for one action."""
    if action.action_type == "cash_dividend" and action.cash_amount is not None:
        if close <= 0:
            return Decimal("1")
        return max((close - action.cash_amount) / close, Decimal("0"))
    if action.action_type in {"split", "bonus_share"} and action.share_ratio is not None:
        return Decimal("1") / (Decimal("1") + action.share_ratio)
    return Decimal("1")
