"""Seed demo portfolio data into the database."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select

from margin.news.models import SourceLevel, make_document_event
from margin.news.repository import NewsRepository
from margin.portfolio.db_models import PortfolioRow, TradeRow
from margin.storage.database import create_database_engine, create_session_factory


def main() -> None:
    engine = create_database_engine()
    session_factory = create_session_factory(engine)

    portfolio_id = "demo"

    with session_factory.begin() as session:
        existing = session.get(PortfolioRow, portfolio_id)
        if existing is None:
            session.add(
                PortfolioRow(
                    portfolio_id=portfolio_id,
                    user_id="demo_user",
                    name="Demo 组合",
                    cash=Decimal("1000000.00000000"),
                    created_at=datetime.now(UTC),
                )
            )
        else:
            print("Demo portfolio already exists")

    trades = [
        ("000001.SZ", "buy", 10000, Decimal("12.50"), "2026-01-15"),
        ("600519.SH", "buy", 500, Decimal("150.00"), "2026-02-01"),
        ("000333.SZ", "buy", 8000, Decimal("45.00"), "2026-03-10"),
        ("300750.SZ", "buy", 2000, Decimal("180.00"), "2026-04-05"),
    ]

    from uuid import uuid4

    with session_factory.begin() as session:
        has_trades = session.scalar(
            select(TradeRow.trade_id)
            .where(TradeRow.portfolio_id == portfolio_id)
            .limit(1)
        )
        if has_trades is None:
            for symbol, side, qty, price, date_str in trades:
                trade_id = f"tr_{uuid4().hex[:12]}"
                qty_dec = Decimal(str(qty))
                amount = qty_dec * price
                session.add(
                    TradeRow(
                        trade_id=trade_id,
                        portfolio_id=portfolio_id,
                        symbol=symbol,
                        side=side,
                        quantity=qty_dec,
                        price=price,
                        amount=amount,
                        fee=Decimal("0"),
                        tax=Decimal("0"),
                        traded_at=datetime.strptime(date_str, "%Y-%m-%d").replace(
                            tzinfo=UTC
                        ),
                        source="manual",
                        imported_at=datetime.now(UTC),
                    )
                )
                print(f"Added trade: {symbol} {side} {qty} @ {price}")
        else:
            print("Demo trades already exist")

    news_repository = NewsRepository(session_factory)
    demo_source_url = "https://example.com/margin/demo-filing"
    if not any(
        event.source_url == demo_source_url
        for event in news_repository.list_unique_events()
    ):
        available_at = datetime(2026, 6, 18, tzinfo=UTC)
        news_repository.add_document_event(
            make_document_event(
                source_url=demo_source_url,
                source_name="margin_demo",
                source_level=SourceLevel.L1,
                title="平安银行经营现金流改善示例公告",
                content=(
                    "平安银行经营现金流改善，资产质量保持稳定。"
                    "该内容仅用于本地端到端功能验证，不构成投资建议。"
                ),
                symbols=["000001.SZ"],
                doc_type="filing",
                published_at=available_at,
                available_at=available_at,
            )
        )
        print("Added demo filing event")
    else:
        print("Demo filing event already exists")

    print("Seed complete!")


if __name__ == "__main__":
    main()
