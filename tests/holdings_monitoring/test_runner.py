"""Tests for the automatic holdings-monitoring runner."""

from __future__ import annotations

from datetime import UTC, datetime

from margin.holdings_monitoring.models import AlertPriority, AlertType
from margin.holdings_monitoring.repository import MemoryMonitoringRepository
from margin.holdings_monitoring.runner import (
    AKShareLatestPriceProvider,
    HoldingsMonitoringRunner,
)
from margin.holdings_monitoring.service import HoldingsMonitoringService
from margin.news.models import SourceLevel, make_document_event
from margin.portfolio.repository import MemoryPortfolioRepository
from margin.portfolio.service import PortfolioService


class FixedPriceProvider:
    def get_latest_prices(
        self,
        symbols: list[str],
        *,
        as_of: datetime,
    ) -> dict[str, float]:
        del as_of
        return {symbol: 8.8 for symbol in symbols}


class RecordingNotifier:
    def __init__(self) -> None:
        self.alert_ids: list[str] = []

    def notify(self, alert) -> None:
        self.alert_ids.append(alert.alert_id)


class StablePriceProvider:
    def get_latest_prices(
        self,
        symbols: list[str],
        *,
        as_of: datetime,
    ) -> dict[str, float]:
        del as_of
        return {symbol: 10.0 for symbol in symbols}


class FixedNewsProvider:
    def get_recent_events(self, symbols, *, since, as_of):
        del since
        return [
            make_document_event(
                source_url="https://example.com/filing",
                source_name="exchange",
                source_level=SourceLevel.L1,
                title="公司收到重大处罚",
                content="监管机构立案并作出处罚",
                symbols=symbols,
                published_at=as_of,
                available_at=as_of,
            )
        ]


class FailingBarProvider:
    def get_bars(self, symbols, start, end):
        del symbols, start, end
        raise RuntimeError("market unavailable")


def test_runner_evaluates_all_positions_and_notifies_high_priority_alerts():
    portfolio_repository = MemoryPortfolioRepository()
    portfolio_service = PortfolioService(repository=portfolio_repository)
    portfolio = portfolio_service.create_portfolio("user_1", "Core", cash=10000)
    portfolio_service.add_trade(
        portfolio.portfolio_id,
        "000001.SZ",
        "buy",
        100,
        10,
        datetime(2026, 6, 1, tzinfo=UTC),
    )
    monitoring_repository = MemoryMonitoringRepository()
    monitoring_service = HoldingsMonitoringService(
        repository=monitoring_repository,
        portfolio_service=portfolio_service,
    )
    notifier = RecordingNotifier()
    runner = HoldingsMonitoringRunner(
        portfolio_service=portfolio_service,
        monitoring_service=monitoring_service,
        price_provider=FixedPriceProvider(),
        notifier=notifier,
    )

    snapshots = runner.run_once(
        decision_at=datetime(2026, 6, 19, 9, 30, tzinfo=UTC)
    )

    assert len(snapshots) == 1
    assert snapshots[0].alerts[0].severity == AlertPriority.P0
    assert notifier.alert_ids == [snapshots[0].alerts[0].alert_id]


def test_runner_suppresses_duplicate_notifications_during_cooldown():
    portfolio_repository = MemoryPortfolioRepository()
    portfolio_service = PortfolioService(repository=portfolio_repository)
    portfolio = portfolio_service.create_portfolio("user_1", "Core", cash=10000)
    portfolio_service.add_trade(
        portfolio.portfolio_id,
        "000001.SZ",
        "buy",
        100,
        10,
        datetime(2026, 6, 1, tzinfo=UTC),
    )
    monitoring_repository = MemoryMonitoringRepository()
    monitoring_service = HoldingsMonitoringService(
        repository=monitoring_repository,
        portfolio_service=portfolio_service,
    )
    notifier = RecordingNotifier()
    runner = HoldingsMonitoringRunner(
        portfolio_service=portfolio_service,
        monitoring_service=monitoring_service,
        price_provider=FixedPriceProvider(),
        notifier=notifier,
    )
    first_at = datetime(2026, 6, 19, 9, 30, tzinfo=UTC)

    first = runner.run_once(decision_at=first_at)
    second = runner.run_once(
        decision_at=first_at.replace(minute=35),
    )

    assert len(first[0].alerts) == 1
    assert second[0].alerts == []
    assert len(monitoring_repository.list_alerts(portfolio.portfolio_id)) == 1
    assert notifier.alert_ids == [first[0].alerts[0].alert_id]


def test_runner_turns_trusted_negative_news_into_priority_alert():
    portfolio_service = PortfolioService(repository=MemoryPortfolioRepository())
    portfolio = portfolio_service.create_portfolio("user_1", "Core", cash=10000)
    portfolio_service.add_trade(
        portfolio.portfolio_id,
        "000001.SZ",
        "buy",
        100,
        10,
        datetime(2026, 6, 1, tzinfo=UTC),
    )
    monitoring_service = HoldingsMonitoringService(
        repository=MemoryMonitoringRepository(),
        portfolio_service=portfolio_service,
    )
    runner = HoldingsMonitoringRunner(
        portfolio_service=portfolio_service,
        monitoring_service=monitoring_service,
        price_provider=StablePriceProvider(),
        news_provider=FixedNewsProvider(),
    )

    snapshots = runner.run_once(
        decision_at=datetime(2026, 6, 19, 9, 30, tzinfo=UTC)
    )

    assert snapshots[0].alerts[0].alert_type == AlertType.NEGATIVE_EVENT
    assert snapshots[0].alerts[0].severity == AlertPriority.P1
    assert snapshots[0].alerts[0].evidence_refs


def test_akshare_price_adapter_degrades_to_missing_prices():
    provider = AKShareLatestPriceProvider(FailingBarProvider())

    prices = provider.get_latest_prices(
        ["000001.SZ"],
        as_of=datetime(2026, 6, 19, tzinfo=UTC),
    )

    assert prices == {}
