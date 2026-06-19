"""Automatic holdings-monitoring sweep and local notification adapters."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Protocol

from margin.data.providers.akshare_provider import AKShareProvider
from margin.holdings_monitoring.models import (
    AlertEvent,
    AlertPriority,
    PositionMonitoringSnapshot,
)
from margin.holdings_monitoring.service import HoldingsMonitoringService
from margin.news.models import DocumentEvent
from margin.news.repository import NewsRepository
from margin.portfolio.service import PortfolioService

logger = logging.getLogger(__name__)


class LatestPriceProvider(Protocol):
    """Resolve latest prices for a batch of standardized symbols."""

    def get_latest_prices(
        self,
        symbols: list[str],
        *,
        as_of: datetime,
    ) -> dict[str, float]:
        """Return latest available prices keyed by symbol."""


class NotificationSink(Protocol):
    """Deliver high-priority monitoring alerts."""

    def notify(self, alert: AlertEvent) -> None:
        """Deliver one alert."""


class NewsEventProvider(Protocol):
    """Resolve new, already snapshotted document events for held symbols."""

    def get_recent_events(
        self,
        symbols: list[str],
        *,
        since: datetime,
        as_of: datetime,
    ) -> list[DocumentEvent]:
        """Return events available in the requested time window."""


class RepositoryNewsEventProvider:
    """Read the module 03 document-event stream for holdings monitoring."""

    def __init__(self, repository: NewsRepository) -> None:
        self._repository = repository

    def get_recent_events(
        self,
        symbols: list[str],
        *,
        since: datetime,
        as_of: datetime,
    ) -> list[DocumentEvent]:
        symbol_set = set(symbols)
        return [
            event
            for event in self._repository.list_unique_events()
            if symbol_set.intersection(event.symbols)
            and since < event.available_at <= as_of
        ]


class LoggingNotificationSink:
    """Local-first notification sink backed by structured application logs."""

    def notify(self, alert: AlertEvent) -> None:
        logger.warning(
            "holdings_monitoring_alert",
            extra={
                "alert_id": alert.alert_id,
                "portfolio_id": alert.portfolio_id,
                "position_id": alert.position_id,
                "symbol": alert.symbol,
                "severity": alert.severity.value,
                "rule_name": alert.rule_name,
            },
        )


class AKShareLatestPriceProvider:
    """Latest-price adapter using adjusted daily bars from AKShare."""

    def __init__(self, provider: AKShareProvider | None = None) -> None:
        self._provider = provider or AKShareProvider()

    def get_latest_prices(
        self,
        symbols: list[str],
        *,
        as_of: datetime,
    ) -> dict[str, float]:
        if not symbols:
            return {}
        try:
            bars = self._provider.get_bars(
                symbols,
                as_of - timedelta(days=14),
                as_of,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "latest_price_provider_degraded",
                extra={
                    "provider": "akshare",
                    "symbol_count": len(symbols),
                    "error_type": type(exc).__name__,
                },
            )
            return {}
        latest: dict[str, tuple[datetime, float]] = {}
        for bar in bars:
            symbol = str(bar["symbol"])
            bar_date = bar["date"]
            if not isinstance(bar_date, datetime):
                continue
            candidate = (bar_date, float(bar["close"]))
            if symbol not in latest or candidate[0] > latest[symbol][0]:
                latest[symbol] = candidate
        return {symbol: value for symbol, (_, value) in latest.items()}


class HoldingsMonitoringRunner:
    """Evaluate every persisted position using current market prices."""

    def __init__(
        self,
        *,
        portfolio_service: PortfolioService,
        monitoring_service: HoldingsMonitoringService,
        price_provider: LatestPriceProvider,
        news_provider: NewsEventProvider | None = None,
        notifier: NotificationSink | None = None,
    ) -> None:
        self._portfolios = portfolio_service
        self._monitoring = monitoring_service
        self._prices = price_provider
        self._news = news_provider
        self._notifier = notifier or LoggingNotificationSink()
        self._last_news_check: datetime | None = None

    def run_once(
        self,
        *,
        decision_at: datetime | None = None,
    ) -> list[PositionMonitoringSnapshot]:
        """Run one monitoring sweep for all local portfolios."""
        evaluated_at = decision_at or datetime.now(UTC)
        news_since = self._last_news_check or evaluated_at - timedelta(days=1)
        snapshots: list[PositionMonitoringSnapshot] = []
        for portfolio in self._portfolios.list_portfolios():
            positions = self._portfolios.get_positions(portfolio.portfolio_id)
            symbols = [position.symbol for position in positions]
            prices = self._prices.get_latest_prices(
                symbols,
                as_of=evaluated_at,
            )
            news_events = (
                self._news.get_recent_events(
                    symbols,
                    since=news_since,
                    as_of=evaluated_at,
                )
                if self._news is not None
                else []
            )
            priced_positions = self._portfolios.get_positions(
                portfolio.portfolio_id,
                prices,
            )
            for position in priced_positions:
                snapshot = self._monitoring.evaluate_position(
                    portfolio_id=portfolio.portfolio_id,
                    position=position,
                    thesis=position.thesis,
                    current_price=prices.get(position.symbol),
                    news_events=news_events,
                    decision_at=evaluated_at,
                )
                snapshots.append(snapshot)
                for alert in snapshot.alerts:
                    if alert.severity in {AlertPriority.P0, AlertPriority.P1}:
                        try:
                            self._notifier.notify(alert)
                        except Exception:  # noqa: BLE001
                            logger.exception(
                                "holdings_monitoring_notification_failed",
                                extra={"alert_id": alert.alert_id},
                            )
        self._last_news_check = evaluated_at
        return snapshots
