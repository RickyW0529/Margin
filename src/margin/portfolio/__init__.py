"""Portfolio package for trade entry, cost calculation, and portfolio risk.

This package exposes the core building blocks used to manage investment
portfolios: recording trades, calculating position cost basis, importing
transactions from brokers or files, tracking investment theses, and
aggregating portfolio-level risk metrics.
"""

from margin.portfolio.cost import CostCalculator
from margin.portfolio.importer import (
    BrokerImportPlugin,
    ImportValidationError,
    TradeImporter,
    TradeValidationError,
    compute_raw_hash,
    validate_trade_fields,
)
from margin.portfolio.models import (
    AlertEvent,
    ImportRecord,
    Portfolio,
    Position,
    PositionHealthStatus,
    PositionThesis,
    ThesisStatus,
    Trade,
    TradeSide,
    TradeSource,
    make_trade,
)
from margin.portfolio.risk import PortfolioRiskEngine, PortfolioRiskReport, RiskMetric
from margin.portfolio.service import (
    PortfolioOverview,
    PortfolioService,
    PositionDetail,
)

__all__ = [
    "AlertEvent",
    "BrokerImportPlugin",
    "CostCalculator",
    "ImportRecord",
    "ImportValidationError",
    "Portfolio",
    "PortfolioOverview",
    "PortfolioRiskEngine",
    "PortfolioRiskReport",
    "PortfolioService",
    "Position",
    "PositionDetail",
    "PositionHealthStatus",
    "PositionThesis",
    "RiskMetric",
    "ThesisStatus",
    "Trade",
    "TradeImporter",
    "TradeSide",
    "TradeSource",
    "TradeValidationError",
    "compute_raw_hash",
    "make_trade",
    "validate_trade_fields",
]
