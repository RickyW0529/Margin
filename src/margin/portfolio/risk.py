"""Portfolio risk engine — eight-dimensional risk measurement.

Corresponds to spec 02 §4 data model (architecture §17.2 portfolio risk).
Corresponds to plan 0202.2 / 0202.3 / 0202.4.

The eight dimensions (architecture §17.2) are:
1. single_position
2. industry_concentration
3. style_exposure
4. correlation
5. liquidity
6. volatility
7. drawdown
8. event_concentration
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from margin.portfolio.models import Position, PositionHealthStatus


class RiskMetric(BaseModel):
    """A single risk metric.

    Attributes:
        name: Machine-readable identifier for the metric.
        value: Computed metric value.
        threshold: Optional limit against which the value is compared.
        breached: Whether the value exceeds the threshold.
        details: Additional context, such as weights or per-symbol breakdowns.
    """

    name: str
    value: float
    threshold: float | None = None
    breached: bool = False
    details: dict[str, Any] = Field(default_factory=dict)

    model_config = {"frozen": True}


class PortfolioRiskReport(BaseModel):
    """Portfolio risk report (corresponds to GET /portfolios/{id}/risk).

    Attributes:
        portfolio_id: Identifier of the evaluated portfolio.
        total_value: Total market value of the evaluated long positions.
        metrics: List of computed risk metrics.
        computed_at: Timestamp when the report was generated.
        max_single_position: Threshold for the largest single-position weight.
        max_industry_exposure: Threshold for the largest industry exposure.
    """

    portfolio_id: str
    total_value: float = 0.0
    metrics: list[RiskMetric] = Field(default_factory=list)
    computed_at: datetime = Field(default_factory=lambda: datetime.now())
    max_single_position: float = 0.05
    max_industry_exposure: float = 0.20

    @property
    def has_breach(self) -> bool:
        """Whether any metric in the report breaches its threshold."""
        return any(m.breached for m in self.metrics)

    @property
    def breached_metrics(self) -> list[RiskMetric]:
        """Return only the metrics that have breached their thresholds."""
        return [m for m in self.metrics if m.breached]


class PortfolioRiskEngine:
    """Portfolio risk engine.

    Computes risk metrics across eight dimensions and compares them against strategy thresholds.
    When market data is missing the engine falls back to single-position validation and avoids
    high-confidence portfolio-wide conclusions (corresponds to spec 02 §7).

    Attributes:
        _max_single: Maximum allowed weight for a single position.
        _max_industry: Maximum allowed exposure to a single industry.
    """

    def __init__(
        self,
        max_single_position: float = 0.05,
        max_industry_exposure: float = 0.20,
    ) -> None:
        """Initialize the risk engine with portfolio-level thresholds.

        Args:
            max_single_position: Upper limit for a single position's portfolio weight.
            max_industry_exposure: Upper limit for a single industry's portfolio weight.
        """
        self._max_single = max_single_position
        self._max_industry = max_industry_exposure

    def calculate(
        self,
        portfolio_id: str,
        positions: list[Position],
        prices_history: dict[str, list[float]] | None = None,
        upcoming_events: dict[str, datetime] | None = None,
    ) -> PortfolioRiskReport:
        """Compute the full portfolio risk report.

        Args:
            portfolio_id: Identifier of the portfolio being evaluated.
            positions: List of positions. Each position must provide a market_value.
            prices_history: Historical price series per symbol, used for volatility and drawdown.
            upcoming_events: Mapping from symbol to upcoming event date, used for event risk.

        Returns:
            A PortfolioRiskReport containing all computed metrics.
        """
        long_positions = [p for p in positions if p.quantity > 0]
        total_value = sum(p.market_value or 0 for p in long_positions)
        missing_positions = [
            p for p in long_positions
            if p.market_value is None
            or p.health_status == PositionHealthStatus.DATA_MISSING
        ]

        if missing_positions:
            metrics = [
                RiskMetric(
                    name="data_missing",
                    value=len(missing_positions) / len(long_positions)
                    if long_positions else 1.0,
                    threshold=0.0,
                    breached=True,
                    details={
                        "reason": "Missing market value for one or more positions",
                        "symbols": [p.symbol for p in missing_positions],
                    },
                )
            ]

            priced_positions = [p for p in long_positions if p.market_value is not None]
            if total_value > 0 and priced_positions:
                metrics.append(self._single_position_risk(priced_positions, total_value))

            return PortfolioRiskReport(
                portfolio_id=portfolio_id,
                total_value=total_value,
                metrics=metrics,
                max_single_position=self._max_single,
                max_industry_exposure=self._max_industry,
            )

        if total_value <= 0:
            return PortfolioRiskReport(
                portfolio_id=portfolio_id,
                total_value=0.0,
                metrics=[
                    RiskMetric(
                        name="data_missing",
                        value=1.0,
                        threshold=0.0,
                        breached=True,
                        details={"reason": "No market value available"},
                    )
                ],
                max_single_position=self._max_single,
                max_industry_exposure=self._max_industry,
            )

        metrics: list[RiskMetric] = []

        metrics.append(self._single_position_risk(long_positions, total_value))
        metrics.append(self._industry_concentration(long_positions, total_value))
        metrics.append(self._style_exposure(long_positions, total_value))
        metrics.append(self._correlation_risk(long_positions))
        metrics.append(self._liquidity_risk(long_positions, total_value))

        if prices_history:
            metrics.append(self._volatility(long_positions, prices_history))
            metrics.append(self._drawdown(long_positions, prices_history))
        else:
            metrics.append(
                RiskMetric(
                    name="volatility",
                    value=0.0,
                    details={"note": "No price history available, skipped"},
                )
            )
            metrics.append(
                RiskMetric(
                    name="drawdown",
                    value=0.0,
                    details={"note": "No price history available, skipped"},
                )
            )

        metrics.append(
            self._event_concentration(long_positions, upcoming_events or {})
        )

        return PortfolioRiskReport(
            portfolio_id=portfolio_id,
            total_value=total_value,
            metrics=metrics,
            max_single_position=self._max_single,
            max_industry_exposure=self._max_industry,
        )

    def _single_position_risk(
        self, positions: list[Position], total_value: float
    ) -> RiskMetric:
        """Dimension 1: maximum single-position weight.

        Args:
            positions: Positions to evaluate.
            total_value: Total market value of the evaluated positions.

        Returns:
            RiskMetric for single-position concentration.
        """
        weights = {
            p.symbol: (p.market_value or 0) / total_value for p in positions
        }
        max_weight = max(weights.values()) if weights else 0.0
        max_symbol = max(weights, key=weights.get) if weights else ""

        return RiskMetric(
            name="single_position",
            value=max_weight,
            threshold=self._max_single,
            breached=max_weight > self._max_single,
            details={
                "max_symbol": max_symbol,
                "weights": {k: round(v, 4) for k, v in weights.items()},
            },
        )

    def _industry_concentration(
        self, positions: list[Position], total_value: float
    ) -> RiskMetric:
        """Dimension 2: industry concentration.

        Args:
            positions: Positions to evaluate.
            total_value: Total market value of the evaluated positions.

        Returns:
            RiskMetric for the largest industry exposure.
        """
        industry_values: dict[str, float] = {}
        for p in positions:
            industry = p.industry or "unknown"
            industry_values[industry] = (
                industry_values.get(industry, 0) + (p.market_value or 0)
            )

        industry_weights = {
            ind: val / total_value for ind, val in industry_values.items()
        }
        max_exposure = max(industry_weights.values()) if industry_weights else 0.0
        max_industry = (
            max(industry_weights, key=industry_weights.get)
            if industry_weights
            else ""
        )

        return RiskMetric(
            name="industry_concentration",
            value=max_exposure,
            threshold=self._max_industry,
            breached=max_exposure > self._max_industry,
            details={
                "max_industry": max_industry,
                "weights": {k: round(v, 4) for k, v in industry_weights.items()},
            },
        )

    def _style_exposure(
        self, positions: list[Position], total_value: float
    ) -> RiskMetric:
        """Dimension 3: style exposure (simplified growth/value split).

        A position is classified as growth when its current price is more than 20% above cost.
        Otherwise it is treated as value.

        Args:
            positions: Positions to evaluate.
            total_value: Total market value of the evaluated positions.

        Returns:
            RiskMetric with growth and value weights.
        """
        growth_value = 0.0
        value_value = 0.0

        for p in positions:
            mv = p.market_value or 0
            if p.cost_price > 0 and p.current_price and p.current_price / p.cost_price > 1.2:
                growth_value += mv
            else:
                value_value += mv

        growth_weight = growth_value / total_value if total_value > 0 else 0.0
        value_weight = value_value / total_value if total_value > 0 else 0.0

        return RiskMetric(
            name="style_exposure",
            value=growth_weight,
            details={
                "growth_weight": round(growth_weight, 4),
                "value_weight": round(value_weight, 4),
            },
        )

    def _correlation_risk(self, positions: list[Position]) -> RiskMetric:
        """Dimension 4: correlation risk (simplified proxy via industry clustering).

        Args:
            positions: Positions to evaluate.

        Returns:
            RiskMetric for industry-based correlation concentration.
        """
        industry_groups: dict[str, int] = {}
        for p in positions:
            industry = p.industry or "unknown"
            industry_groups[industry] = industry_groups.get(industry, 0) + 1

        max_same_industry = max(industry_groups.values()) if industry_groups else 0
        concentration = max_same_industry / len(positions) if positions else 0.0

        return RiskMetric(
            name="correlation",
            value=concentration,
            details={
                "industry_groups": industry_groups,
                "max_same_industry": max_same_industry,
            },
        )

    def _liquidity_risk(
        self, positions: list[Position], total_value: float
    ) -> RiskMetric:
        """Dimension 5: liquidity risk (simplified proxy based on position weight).

        Args:
            positions: Positions to evaluate.
            total_value: Total market value of the evaluated positions.

        Returns:
            RiskMetric for liquidity concentration.
        """
        max_position_value = max(
            (p.market_value or 0) for p in positions
        ) if positions else 0.0
        liquidity_ratio = max_position_value / total_value if total_value > 0 else 0.0

        return RiskMetric(
            name="liquidity",
            value=liquidity_ratio,
            details={
                "max_position_value": max_position_value,
                "note": "Simplified: uses position weight as liquidity proxy",
            },
        )

    def _volatility(
        self, positions: list[Position], prices_history: dict[str, list[float]]
    ) -> RiskMetric:
        """Dimension 6: volatility (position-weighted daily return standard deviation).

        Args:
            positions: Positions to evaluate.
            prices_history: Historical price series per symbol.

        Returns:
            RiskMetric for weighted portfolio volatility.
        """
        import math

        weighted_vol = 0.0
        total_mv = sum(p.market_value or 0 for p in positions)

        for p in positions:
            history = prices_history.get(p.symbol, [])
            if len(history) < 2:
                continue
            returns = [
                (history[i] - history[i - 1]) / history[i - 1]
                for i in range(1, len(history))
                if history[i - 1] != 0
            ]
            if not returns:
                continue
            mean_ret = sum(returns) / len(returns)
            variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
            vol = math.sqrt(variance)
            weight = (p.market_value or 0) / total_mv if total_mv > 0 else 0
            weighted_vol += vol * weight

        return RiskMetric(
            name="volatility",
            value=weighted_vol,
            details={"annualized_estimate": weighted_vol * math.sqrt(252)},
        )

    def _drawdown(
        self, positions: list[Position], prices_history: dict[str, list[float]]
    ) -> RiskMetric:
        """Dimension 7: drawdown (position-weighted maximum drawdown).

        Args:
            positions: Positions to evaluate.
            prices_history: Historical price series per symbol.

        Returns:
            RiskMetric for weighted maximum drawdown.
        """
        weighted_dd = 0.0
        total_mv = sum(p.market_value or 0 for p in positions)

        for p in positions:
            history = prices_history.get(p.symbol, [])
            if len(history) < 2:
                continue
            peak = history[0]
            max_dd = 0.0
            for price in history[1:]:
                if price > peak:
                    peak = price
                dd = (peak - price) / peak if peak > 0 else 0.0
                if dd > max_dd:
                    max_dd = dd
            weight = (p.market_value or 0) / total_mv if total_mv > 0 else 0
            weighted_dd += max_dd * weight

        return RiskMetric(
            name="drawdown",
            value=weighted_dd,
            details={"note": "Weighted max drawdown across positions"},
        )

    def _event_concentration(
        self, positions: list[Position], upcoming_events: dict[str, datetime]
    ) -> RiskMetric:
        """Dimension 8: event concentration risk (corresponds to plan 0202.3).

        Args:
            positions: Positions to evaluate.
            upcoming_events: Mapping from symbol to upcoming event date.

        Returns:
            RiskMetric for the share of positions with events within 30 days.
        """
        now = datetime.now()
        events_30d: list[str] = []

        for p in positions:
            event_date = upcoming_events.get(p.symbol)
            if event_date and 0 <= (event_date - now).days <= 30:
                events_30d.append(p.symbol)

        concentration = len(events_30d) / len(positions) if positions else 0.0

        return RiskMetric(
            name="event_concentration",
            value=concentration,
            details={
                "symbols_with_events_30d": events_30d,
                "event_count": len(events_30d),
            },
        )
