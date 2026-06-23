"""PIT dimension tests for security, industry, and corporate actions."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from margin.data.corporate_actions import CorporateAction, CorporateActionAdjuster, PriceBar
from margin.data.industry import BitemporalIndustryResolver, IndustryMembership

SECURITY = "000001.SZ"
BUSINESS_DAY = date(2024, 1, 2)
SYSTEM_OLD = datetime(2024, 1, 10, tzinfo=UTC)
SYSTEM_NEW = datetime(2024, 2, 10, tzinfo=UTC)
DECISION = datetime(2024, 6, 22, tzinfo=UTC)


def test_industry_query_uses_business_and_system_time() -> None:
    """industry query uses business and system time."""
    resolver = BitemporalIndustryResolver(
        [
            IndustryMembership(
                security_id=SECURITY,
                taxonomy="citics",
                industry_code="OLD",
                industry_name="旧行业",
                valid_from=date(2024, 1, 1),
                valid_to=None,
                system_from=datetime(2024, 1, 1, tzinfo=UTC),
                system_to=datetime(2024, 2, 1, tzinfo=UTC),
                source="test",
                quality="ok",
            ),
            IndustryMembership(
                security_id=SECURITY,
                taxonomy="citics",
                industry_code="NEW",
                industry_name="新行业",
                valid_from=date(2024, 1, 1),
                valid_to=None,
                system_from=datetime(2024, 2, 1, tzinfo=UTC),
                system_to=None,
                source="test",
                quality="ok",
            ),
        ]
    )

    assert resolver.resolve(SECURITY, "citics", BUSINESS_DAY, SYSTEM_OLD).industry_code == "OLD"
    assert resolver.resolve(SECURITY, "citics", BUSINESS_DAY, SYSTEM_NEW).industry_code == "NEW"


def test_adjustment_ignores_future_announced_dividend() -> None:
    """adjustment ignores future announced dividend."""
    prices = [
        PriceBar(security_id=SECURITY, trade_date=date(2024, 6, 21), close=Decimal("10")),
        PriceBar(security_id=SECURITY, trade_date=date(2024, 6, 22), close=Decimal("11")),
    ]
    actions = [
        CorporateAction(
            security_id=SECURITY,
            action_type="cash_dividend",
            ex_date=date(2024, 6, 22),
            cash_amount=Decimal("1"),
            available_at=DECISION + timedelta(days=1),
        )
    ]

    series = CorporateActionAdjuster(policy_version="adjust-v0.2.0").build_as_of(
        prices,
        actions,
        decision_at=DECISION,
    )

    assert series[-1].adjustment_factor == Decimal("1")
    assert series[-1].adj_close == Decimal("11")
