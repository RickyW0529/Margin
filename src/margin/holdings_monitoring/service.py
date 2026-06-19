"""Services for module 09 holdings monitoring."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from margin.holdings_monitoring.models import (
    AlertEvent,
    AlertPriority,
    AlertType,
    BehaviorMetric,
    OperationHistoryEntry,
    PositionMonitoringSnapshot,
    PositionReviewRecord,
    ReviewDecision,
)
from margin.holdings_monitoring.repository import (
    MemoryMonitoringRepository,
    MonitoringRepository,
)
from margin.news.models import DocumentEvent
from margin.portfolio.models import (
    Position,
    PositionHealthStatus,
    PositionThesis,
    ThesisStatus,
    Trade,
)
from margin.portfolio.service import PortfolioService

PRICE_INVALIDATION_DRAWDOWN = 0.10
PRICE_RISK_DRAWDOWN = 0.05
ALERT_COOLDOWN = timedelta(hours=6)


class HoldingsMonitoringService:
    """Deterministic holdings monitoring service for intraday-safe checks."""

    def __init__(
        self,
        repository: MonitoringRepository | None = None,
        portfolio_service: PortfolioService | None = None,
    ) -> None:
        self._repository = repository or MemoryMonitoringRepository()
        self._portfolio_service = portfolio_service

    def evaluate_position(
        self,
        *,
        portfolio_id: str,
        position: Position,
        thesis: PositionThesis | None,
        current_price: float | None = None,
        evidence_refs: list[str] | None = None,
        model_rank_delta: float | None = None,
        industry_exposure: float | None = None,
        strategy_failure: bool = False,
        upcoming_event_at: datetime | None = None,
        news_events: list[DocumentEvent] | None = None,
        decision_at: datetime | None = None,
    ) -> PositionMonitoringSnapshot:
        """Evaluate one position with deterministic monitoring rules."""
        evaluated_at = _ensure_dt(decision_at)
        evidence_refs = evidence_refs or []
        news_events = news_events or []
        resolved_price = current_price if current_price is not None else position.current_price
        alerts: list[AlertEvent] = []
        reasons: list[str] = []
        health_status = PositionHealthStatus.HEALTHY
        thesis_status = thesis.status if thesis else ThesisStatus.THESIS_VALID
        data_missing = False

        if resolved_price is None:
            data_missing = True
            health_status = PositionHealthStatus.DATA_MISSING
            reasons.append("价格数据缺失，停止输出高置信持仓判断")
            alerts.append(
                self._build_alert(
                    portfolio_id=portfolio_id,
                    position=position,
                    alert_type=AlertType.DATA_QUALITY,
                    severity=AlertPriority.P2,
                    rule_name="data_missing_price",
                    message="价格数据缺失，已降级为 DATA_MISSING",
                    triggered_at=evaluated_at,
                    evidence_refs=evidence_refs,
                )
            )
        elif position.cost_price > 0 and resolved_price <= position.cost_price * (
            1 - PRICE_INVALIDATION_DRAWDOWN
        ):
            health_status = PositionHealthStatus.INVALIDATED
            thesis_status = ThesisStatus.THESIS_INVALIDATED
            reasons.append("价格触及投资逻辑失效阈值")
            alerts.append(
                self._build_alert(
                    portfolio_id=portfolio_id,
                    position=position,
                    alert_type=AlertType.PRICE_INVALIDATION,
                    severity=AlertPriority.P0,
                    rule_name="price_invalidation",
                    message="价格触及失效条件，投资逻辑需要立即复核",
                    triggered_at=evaluated_at,
                    evidence_refs=evidence_refs,
                    changed_thesis=True,
                )
            )
        elif position.cost_price > 0 and resolved_price <= position.cost_price * (
            1 - PRICE_RISK_DRAWDOWN
        ):
            health_status = PositionHealthStatus.RISK
            thesis_status = ThesisStatus.RISK_ALERT
            reasons.append("价格接近投资逻辑失效阈值")
            alerts.append(
                self._build_alert(
                    portfolio_id=portfolio_id,
                    position=position,
                    alert_type=AlertType.PRICE_INVALIDATION,
                    severity=AlertPriority.P1,
                    rule_name="price_risk",
                    message="价格接近失效条件，交易时段需要复核",
                    triggered_at=evaluated_at,
                    evidence_refs=evidence_refs,
                )
            )

        if thesis and thesis.next_review_at and thesis.next_review_at <= evaluated_at:
            if health_status == PositionHealthStatus.HEALTHY:
                health_status = PositionHealthStatus.EVENT_PENDING
            reasons.append("持仓到达下一次复核时间")
            alerts.append(
                self._build_alert(
                    portfolio_id=portfolio_id,
                    position=position,
                    alert_type=AlertType.KEY_EVENT_PENDING,
                    severity=AlertPriority.P2,
                    rule_name="next_review_due",
                    message="持仓到达计划复核时间",
                    triggered_at=evaluated_at,
                    evidence_refs=evidence_refs,
                )
            )

        if strategy_failure:
            if health_status == PositionHealthStatus.HEALTHY:
                health_status = PositionHealthStatus.WATCH
            reasons.append("策略运行失败，进入降级观察")
            alerts.append(
                self._build_alert(
                    portfolio_id=portfolio_id,
                    position=position,
                    alert_type=AlertType.STRATEGY_FAILURE,
                    severity=AlertPriority.P2,
                    rule_name="strategy_failure",
                    message="策略运行失败，已降级为规则型提醒",
                    triggered_at=evaluated_at,
                    evidence_refs=evidence_refs,
                )
            )

        if model_rank_delta is not None and model_rank_delta <= -30:
            if health_status == PositionHealthStatus.HEALTHY:
                health_status = PositionHealthStatus.WATCH
            reasons.append("模型排名明显下降")
            alerts.append(
                self._build_alert(
                    portfolio_id=portfolio_id,
                    position=position,
                    alert_type=AlertType.MODEL_RANK_CHANGE,
                    severity=AlertPriority.P2,
                    rule_name="model_rank_drop",
                    message="模型排名明显下降，进入观察",
                    triggered_at=evaluated_at,
                    evidence_refs=evidence_refs,
                )
            )

        if industry_exposure is not None and industry_exposure >= 0.35:
            if health_status == PositionHealthStatus.HEALTHY:
                health_status = PositionHealthStatus.WATCH
            reasons.append("行业暴露超过监控阈值")
            alerts.append(
                self._build_alert(
                    portfolio_id=portfolio_id,
                    position=position,
                    alert_type=AlertType.INDUSTRY_EXPOSURE,
                    severity=AlertPriority.P2,
                    rule_name="industry_exposure_limit",
                    message="行业暴露超过监控阈值",
                    triggered_at=evaluated_at,
                    evidence_refs=evidence_refs,
                )
            )

        if upcoming_event_at is not None:
            if health_status == PositionHealthStatus.HEALTHY:
                health_status = PositionHealthStatus.EVENT_PENDING
            reasons.append("关键事件即将发生")
            alerts.append(
                self._build_alert(
                    portfolio_id=portfolio_id,
                    position=position,
                    alert_type=AlertType.KEY_EVENT_PENDING,
                    severity=AlertPriority.P2,
                    rule_name="upcoming_key_event",
                    message="关键事件即将发生",
                    triggered_at=evaluated_at,
                    evidence_refs=evidence_refs,
                )
            )

        negative_terms = (
            "处罚",
            "立案",
            "亏损",
            "下修",
            "违约",
            "诉讼",
            "减持",
            "风险",
        )
        for event in news_events:
            if position.symbol not in event.symbols or event.available_at > evaluated_at:
                continue
            event_refs = sorted({*evidence_refs, event.event_id})
            text = f"{event.title}\n{event.content or ''}"
            is_negative = any(term in text for term in negative_terms)
            if is_negative and event.can_change_research_state:
                if health_status not in {
                    PositionHealthStatus.INVALIDATED,
                    PositionHealthStatus.DATA_MISSING,
                }:
                    health_status = PositionHealthStatus.RISK
                    thesis_status = ThesisStatus.RISK_ALERT
                reasons.append(f"可信来源出现重大负面事件：{event.title}")
                alerts.append(
                    self._build_alert(
                        portfolio_id=portfolio_id,
                        position=position,
                        alert_type=AlertType.NEGATIVE_EVENT,
                        severity=AlertPriority.P1,
                        rule_name=f"negative_event:{event.event_id}",
                        message=f"重大负面事件需要复核：{event.title}",
                        triggered_at=evaluated_at,
                        evidence_refs=event_refs,
                        changed_thesis=True,
                    )
                )
            else:
                if health_status == PositionHealthStatus.HEALTHY:
                    health_status = PositionHealthStatus.EVENT_PENDING
                reasons.append(f"发现新公告或新闻：{event.title}")
                alerts.append(
                    self._build_alert(
                        portfolio_id=portfolio_id,
                        position=position,
                        alert_type=AlertType.NEW_DISCLOSURE,
                        severity=AlertPriority.P2,
                        rule_name=f"new_disclosure:{event.event_id}",
                        message=f"发现新公告或新闻：{event.title}",
                        triggered_at=evaluated_at,
                        evidence_refs=event_refs,
                    )
                )

        emitted_alerts: list[AlertEvent] = []
        for alert in alerts:
            latest = self._repository.get_latest_alert(
                alert.portfolio_id,
                alert.position_id,
                alert.rule_name,
            )
            if (
                latest is not None
                and alert.triggered_at - latest.triggered_at < ALERT_COOLDOWN
            ):
                continue
            self._repository.add_alert(alert)
            emitted_alerts.append(alert)

        return PositionMonitoringSnapshot(
            position_id=position.position_id,
            portfolio_id=portfolio_id,
            symbol=position.symbol,
            health_status=health_status,
            thesis_status=thesis_status,
            evaluated_at=evaluated_at,
            reasons=reasons,
            alerts=emitted_alerts,
            data_missing=data_missing,
        )

    def evaluate_position_by_id(
        self,
        *,
        portfolio_id: str,
        position_id: str,
        current_price: float | None = None,
        evidence_refs: list[str] | None = None,
        model_rank_delta: float | None = None,
        industry_exposure: float | None = None,
        strategy_failure: bool = False,
        upcoming_event_at: datetime | None = None,
        decision_at: datetime | None = None,
    ) -> PositionMonitoringSnapshot:
        """Load one position from PortfolioService and evaluate it."""
        if self._portfolio_service is None:
            raise RuntimeError("portfolio service is required for evaluate_position_by_id")
        detail = self._portfolio_service.get_position_detail(portfolio_id, position_id)
        return self.evaluate_position(
            portfolio_id=portfolio_id,
            position=_position_from_detail(detail, portfolio_id),
            thesis=detail.thesis,
            current_price=current_price,
            evidence_refs=evidence_refs,
            model_rank_delta=model_rank_delta,
            industry_exposure=industry_exposure,
            strategy_failure=strategy_failure,
            upcoming_event_at=upcoming_event_at,
            decision_at=decision_at,
        )

    def list_alerts(
        self,
        portfolio_id: str,
        position_id: str | None = None,
    ) -> list[AlertEvent]:
        return self._repository.list_alerts(portfolio_id, position_id)

    def record_review(
        self,
        *,
        portfolio_id: str,
        position_id: str,
        alert_id: str | None,
        decision: ReviewDecision,
        rationale: str,
        action_taken_at: datetime | None = None,
    ) -> PositionReviewRecord:
        if alert_id is not None and self._repository.get_alert(alert_id) is None:
            raise KeyError(f"alert '{alert_id}' not found")
        review = PositionReviewRecord(
            portfolio_id=portfolio_id,
            position_id=position_id,
            alert_id=alert_id,
            decision=decision,
            rationale=rationale,
            action_taken_at=action_taken_at,
        )
        self._repository.add_review(review)
        return review

    def list_reviews(
        self,
        portfolio_id: str,
        position_id: str | None = None,
    ) -> list[PositionReviewRecord]:
        return self._repository.list_reviews(portfolio_id, position_id)

    def get_behavior_metrics(
        self,
        portfolio_id: str,
        position_id: str,
    ) -> list[BehaviorMetric]:
        alerts = {alert.alert_id: alert for alert in self.list_alerts(portfolio_id, position_id)}
        metrics: list[BehaviorMetric] = []
        for review in self.list_reviews(portfolio_id, position_id):
            if review.alert_id is None or review.alert_id not in alerts:
                continue
            alert = alerts[review.alert_id]
            latency = None
            if review.action_taken_at is not None:
                latency = int(
                    (review.action_taken_at - alert.triggered_at).total_seconds()
                )
            metrics.append(
                BehaviorMetric(
                    portfolio_id=portfolio_id,
                    position_id=position_id,
                    alert_id=alert.alert_id,
                    review_id=review.review_id,
                    action_latency_seconds=latency,
                    signal_execution_gap=review.decision.value,
                )
            )
        return metrics

    def get_operation_history(
        self,
        *,
        portfolio_id: str,
        position_id: str,
        trades: list[Trade] | None = None,
    ) -> list[OperationHistoryEntry]:
        resolved_trades = trades
        if resolved_trades is None and self._portfolio_service is not None:
            detail = self._portfolio_service.get_position_detail(portfolio_id, position_id)
            resolved_trades = []
            for item in detail.trade_history:
                resolved_trades.append(
                    Trade(
                        trade_id=str(item["trade_id"]),
                        portfolio_id=portfolio_id,
                        symbol=detail.symbol,
                        side=str(item["side"]),
                        quantity=float(item["quantity"]),
                        price=float(item["price"]),
                        amount=float(item["amount"]),
                        traded_at=item["traded_at"],
                        source=str(item["source"]),
                    )
                )
        entries: list[OperationHistoryEntry] = []
        for trade in resolved_trades or []:
            entries.append(
                OperationHistoryEntry(
                    event_id=trade.trade_id,
                    position_id=position_id,
                    event_type="trade",
                    occurred_at=trade.traded_at,
                    summary=f"{trade.side.value} {trade.quantity:g} @ {trade.price:g}",
                    metadata={
                        "symbol": trade.symbol,
                        "amount": trade.amount,
                        "source": trade.source.value,
                    },
                )
            )
        for alert in self.list_alerts(portfolio_id, position_id):
            entries.append(
                OperationHistoryEntry(
                    event_id=alert.alert_id,
                    position_id=position_id,
                    event_type="alert",
                    occurred_at=alert.triggered_at,
                    summary=alert.message,
                    metadata={
                        "severity": alert.severity.value,
                        "alert_type": alert.alert_type.value,
                    },
                )
            )
        for review in self.list_reviews(portfolio_id, position_id):
            entries.append(
                OperationHistoryEntry(
                    event_id=review.review_id,
                    position_id=position_id,
                    event_type="review",
                    occurred_at=review.action_taken_at or review.created_at,
                    summary=review.rationale,
                    metadata={
                        "decision": review.decision.value,
                        "alert_id": review.alert_id,
                    },
                )
            )
        return sorted(entries, key=lambda item: (item.occurred_at, item.event_id))

    def _build_alert(
        self,
        *,
        portfolio_id: str,
        position: Position,
        alert_type: AlertType,
        severity: AlertPriority,
        rule_name: str,
        message: str,
        triggered_at: datetime,
        evidence_refs: list[str],
        changed_thesis: bool = False,
    ) -> AlertEvent:
        return AlertEvent(
            portfolio_id=portfolio_id,
            position_id=position.position_id,
            symbol=position.symbol,
            alert_type=alert_type,
            severity=severity,
            message=message,
            rule_name=rule_name,
            triggered_at=triggered_at,
            evidence_refs=evidence_refs,
            changed_thesis=changed_thesis,
        )


@dataclass(frozen=True)
class MonitoringServiceBundle:
    """Container for FastAPI dependency injection."""

    monitoring: HoldingsMonitoringService

    @classmethod
    def in_memory(
        cls,
        *,
        portfolio_service: PortfolioService | None = None,
        repository: MemoryMonitoringRepository | None = None,
    ) -> MonitoringServiceBundle:
        return cls(
            monitoring=HoldingsMonitoringService(
                repository=repository or MemoryMonitoringRepository(),
                portfolio_service=portfolio_service,
            )
        )

    @classmethod
    def from_repositories(
        cls,
        *,
        repository: MonitoringRepository,
        portfolio_service: PortfolioService,
    ) -> MonitoringServiceBundle:
        return cls(
            monitoring=HoldingsMonitoringService(
                repository=repository,
                portfolio_service=portfolio_service,
            )
        )


def _ensure_dt(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _position_from_detail(detail: object, portfolio_id: str) -> Position:
    return Position(
        position_id=getattr(detail, "position_id"),
        portfolio_id=portfolio_id,
        symbol=getattr(detail, "symbol"),
        quantity=getattr(detail, "quantity"),
        cost_price=getattr(detail, "cost_price"),
        cost_amount=getattr(detail, "cost_amount"),
        current_price=getattr(detail, "current_price"),
        market_value=getattr(detail, "market_value"),
        unrealized_pnl=getattr(detail, "unrealized_pnl"),
        unrealized_pnl_pct=getattr(detail, "unrealized_pnl_pct"),
        industry=getattr(detail, "industry"),
        health_status=getattr(detail, "health_status"),
        thesis=getattr(detail, "thesis"),
        updated_at=getattr(detail, "updated_at"),
    )
