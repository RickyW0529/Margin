# 02-holdings — Holdings & Portfolio Management

## Table of Contents

- [Module Overview](#module-overview)
- [File-Level Summaries](#file-level-summaries)
- [Domain Models](#domain-models)
  - [Enums](#enums)
  - [Portfolio](#portfolio)
  - [Position](#position)
  - [Trade](#trade)
  - [PositionThesis](#positionthesis)
  - [ImportRecord](#importrecord)
  - [AlertEvent](#alertevent)
  - [Factory Functions](#factory-functions)
- [Service Layer](#service-layer)
  - [PortfolioOverview](#portfoliooverview)
  - [PositionDetail](#positiondetail)
  - [PortfolioService](#portfolioservice)
- [Repositories](#repositories)
  - [PortfolioRepository Protocol](#portfoliorepository-protocol)
  - [MemoryPortfolioRepository](#memoryportfoliorepository)
  - [SQLAlchemyPortfolioRepository](#sqlalchemycportfoliorepository)
- [Cost Engine](#cost-engine)
- [Risk Engine](#risk-engine)
  - [PortfolioRiskReport and RiskMetric](#portfolioriskreport-and-riskmetric)
  - [PortfolioRiskEngine](#portfolioriskengine)
- [Importer](#importer)
  - [BrokerImportPlugin](#brokerimportplugin)
  - [TradeImporter](#tradeimporter)
  - [Validation Helpers](#validation-helpers)
- [FastAPI Endpoints](#fastapi-endpoints)
- [React Page and Component](#react-page-and-component)
  - [PortfolioPage](#portfoliopage)
  - [PortfolioWorkspace](#portfolioworkspace)
- [Cross-Module Usage Notes](#cross-module-usage-notes)

---

## Module Overview

The `02-holdings` module is the portfolio management core of Margin v0.1. It is responsible for recording trades, calculating position cost basis, importing transactions from manual entry or files, persisting portfolio data, tracking investment theses, and aggregating portfolio-level risk metrics.

Key responsibilities:

- Represent portfolios, positions, trades, theses, and import audit records as immutable domain models.
- Calculate cost basis and profit/loss using the moving weighted average method.
- Provide a repository abstraction with in-memory and SQLAlchemy/PostgreSQL implementations.
- Import trades manually, from CSV/Excel, or through broker-specific plugins.
- Compute an eight-dimensional portfolio risk report.
- Expose service operations consumed by FastAPI routes and the Next.js portfolio page.

---

## File-Level Summaries

| File | Purpose |
|------|---------|
| `/Users/wangruiqi/PycharmProjects/Margin/src/margin/portfolio/__init__.py` | Package exports. Re-exports models, service, repositories, cost/risk engines, and importer helpers. |
| `/Users/wangruiqi/PycharmProjects/Margin/src/margin/portfolio/models.py` | Pydantic domain models: `Portfolio`, `Position`, `Trade`, `PositionThesis`, `ImportRecord`, `AlertEvent`, plus enums and `make_trade`. |
| `/Users/wangruiqi/PycharmProjects/Margin/src/margin/portfolio/db_models.py` | SQLAlchemy ORM rows: `PortfolioRow`, `TradeRow`, `PositionThesisRow`. |
| `/Users/wangruiqi/PycharmProjects/Margin/src/margin/portfolio/repository.py` | `PortfolioRepository` protocol and `MemoryPortfolioRepository` / `SQLAlchemyPortfolioRepository` implementations plus row mappers. |
| `/Users/wangruiqi/PycharmProjects/Margin/src/margin/portfolio/cost.py` | `CostCalculator` and internal `_CostTracker` for moving weighted average cost basis. |
| `/Users/wangruiqi/PycharmProjects/Margin/src/margin/portfolio/risk.py` | `PortfolioRiskEngine`, `PortfolioRiskReport`, and `RiskMetric` for eight-dimensional risk measurement. |
| `/Users/wangruiqi/PycharmProjects/Margin/src/margin/portfolio/importer.py` | `TradeImporter`, `BrokerImportPlugin`, validation exceptions, `validate_trade_fields`, and `compute_raw_hash`. |
| `/Users/wangruiqi/PycharmProjects/Margin/src/margin/portfolio/service.py` | `PortfolioService` integrating persistence, import, cost calculation, risk engine, and dashboard views. |
| `/Users/wangruiqi/PycharmProjects/Margin/src/margin/api/routes/portfolios.py` | FastAPI routes under `/api/v1` for portfolios, positions, trades, imports, risk, and theses. |
| `/Users/wangruiqi/PycharmProjects/Margin/src/margin/api/schemas.py` | Request/response Pydantic schemas used by the portfolio routes. |
| `/Users/wangruiqi/PycharmProjects/Margin/web/app/portfolios/[portfolioId]/page.tsx` | Next.js server component that loads a portfolio dashboard and renders `PortfolioWorkspace`. |
| `/Users/wangruiqi/PycharmProjects/Margin/web/app/portfolios/[portfolioId]/loading.tsx` | Loading UI shown while the portfolio page fetches data. |
| `/Users/wangruiqi/PycharmProjects/Margin/web/app/portfolios/[portfolioId]/page.test.tsx` | Tests for the server page route. |
| `/Users/wangruiqi/PycharmProjects/Margin/web/components/portfolio-workspace.tsx` | Client component that renders the portfolio dashboard, metrics, positions table, exposures, and events. |
| `/Users/wangruiqi/PycharmProjects/Margin/web/components/portfolio-workspace.test.tsx` | Unit tests for `PortfolioWorkspace`. |

---

## Domain Models

All domain models are Pydantic `BaseModel` instances configured as frozen (`model_config = {"frozen": True}`). Timestamps are normalized to UTC via validators.

### Enums

| Enum | Values | Purpose |
|------|--------|---------|
| `TradeSide` | `buy`, `sell`, `dividend`, `split` | Direction or corporate-action type of a trade. |
| `TradeSource` | `manual`, `csv`, `excel`, `broker_plugin` | Origin of a trade record for audit. |
| `PositionHealthStatus` | `healthy`, `watch`, `risk`, `invalidated`, `data_missing`, `event_pending` | Position health classification. |
| `ThesisStatus` | `thesis_valid`, `review_required`, `risk_alert`, `thesis_invalidated` | Lifecycle status of an investment thesis. |

### Portfolio

Represents a user-owned portfolio.

| Field | Type | Description |
|-------|------|-------------|
| `portfolio_id` | `str` | Unique identifier. |
| `user_id` | `str` | Owner identifier. |
| `name` | `str` | Human-readable name. |
| `cash` | `float` | Cash balance. |
| `created_at` | `datetime` | Creation timestamp (UTC). |

### Position

A holding derived from trade records by `CostCalculator`.

| Field | Type | Description |
|-------|------|-------------|
| `position_id` | `str` | Stable identifier derived from `portfolio_id` and `symbol`. |
| `portfolio_id` | `str` | Owning portfolio. |
| `symbol` | `str` | Normalized trading symbol. |
| `quantity` | `float` | Shares or units held. |
| `cost_price` | `float` | Average cost per unit. |
| `cost_amount` | `float` | Total cost amount. |
| `current_price` | `float \| None` | Latest market price. |
| `market_value` | `float \| None` | Current market value. |
| `unrealized_pnl` | `float \| None` | Unrealized profit/loss. |
| `unrealized_pnl_pct` | `float \| None` | Unrealized PnL as a fraction of cost. |
| `industry` | `str \| None` | Industry classification. |
| `health_status` | `PositionHealthStatus` | Health classification. |
| `thesis` | `PositionThesis \| None` | Latest investment thesis. |
| `updated_at` | `datetime` | Last update timestamp. |

### Trade

A single immutable trade record.

| Field | Type | Description |
|-------|------|-------------|
| `trade_id` | `str` | Unique identifier. |
| `portfolio_id` | `str` | Owning portfolio. |
| `symbol` | `str` | Normalized trading symbol. |
| `side` | `TradeSide` | Trade direction. |
| `quantity` | `float` | Units traded. |
| `price` | `float` | Execution price per unit. |
| `amount` | `float` | Total monetary amount; auto-computed if zero. |
| `fee` | `float` | Transaction fee. |
| `tax` | `float` | Transaction tax. |
| `traded_at` | `datetime` | Execution timestamp. |
| `source` | `TradeSource` | Origin. |
| `source_ref` | `str \| None` | External reference. |
| `raw_hash` | `str \| None` | Hash of raw import row. |
| `imported_at` | `datetime` | Creation/import timestamp. |
| `note` | `str \| None` | Free-text note. |

`Trade.model_post_init` computes `amount = quantity * price + fee + tax` when `amount` is `0.0`.

### PositionThesis

Versioned investment thesis attached to a position.

| Field | Type | Description |
|-------|------|-------------|
| `thesis_id` | `str` | Unique identifier for this version. |
| `position_id` | `str` | Associated position. |
| `thesis` | `str` | Narrative rationale. |
| `entry_conditions` | `list[str]` | Conditions justifying entry. |
| `hold_conditions` | `list[str]` | Conditions justifying continued holding. |
| `invalidation_conditions` | `list[str]` | Conditions that invalidate the thesis. |
| `target_horizon` | `list[int]` | Target review windows in days (default `[60, 120]`). |
| `next_review_at` | `datetime \| None` | Scheduled next review. |
| `status` | `ThesisStatus` | Thesis lifecycle status. |
| `version` | `int` | Monotonically increasing version. |
| `created_at` | `datetime` | Version creation timestamp. |

### ImportRecord

Audit record for each import session.

| Field | Type | Description |
|-------|------|-------------|
| `import_id` | `str` | Unique import session identifier. |
| `portfolio_id` | `str` | Target portfolio. |
| `source` | `TradeSource` | Origin. |
| `file_name` | `str \| None` | Imported file name. |
| `trade_count` | `int` | Accepted trades. |
| `rejected_count` | `int` | Rejected rows. |
| `imported_at` | `datetime` | Import timestamp. |
| `raw_hash` | `str \| None` | Hash of raw import data. |
| `errors` | `list[str]` | Validation error messages. |

### AlertEvent

Data structure for a position or thesis alert. The alerting engine itself lives in the holdings monitoring module; this model only defines the shape.

| Field | Type | Description |
|-------|------|-------------|
| `alert_id` | `str` | Unique alert identifier. |
| `position_id` | `str` | Associated position. |
| `alert_type` | `str` | Classification. |
| `severity` | `str` | Severity (default `P2`). |
| `message` | `str` | Human-readable message. |
| `triggered_at` | `datetime` | Trigger timestamp. |
| `evidence_refs` | `list[str]` | Supporting evidence references. |

### Factory Functions

| Function | Signature | Description |
|----------|-----------|-------------|
| `make_trade` | `(portfolio_id, symbol, side, quantity, price, traded_at, **kwargs) -> Trade` | Creates a `Trade` with a generated id and normalized symbol. |

---

## Service Layer

### PortfolioOverview

Dashboard view model returned by `PortfolioService.get_overview`.

| Field | Type | Description |
|-------|------|-------------|
| `portfolio_id` | `str` | Portfolio identifier. |
| `portfolio_name` | `str` | Portfolio name. |
| `total_assets` | `float` | Cash plus market value. |
| `cash` | `float` | Cash balance. |
| `market_value` | `float` | Total market value. |
| `today_pnl` | `float \| None` | Intraday PnL. |
| `cumulative_pnl` | `float` | Cumulative unrealized PnL. |
| `portfolio_volatility` | `float \| None` | Volatility metric from risk engine. |
| `max_drawdown` | `float \| None` | Drawdown metric from risk engine. |
| `industry_exposure` | `dict[str, float]` | Industry-to-weight mapping. |
| `style_exposure` | `dict[str, float]` | Growth/value weights. |
| `high_risk_count` | `int` | Positions flagged as risk or invalidated. |
| `upcoming_events` | `list[dict[str, Any]]` | Upcoming corporate events. |
| `position_count` | `int` | Number of positions. |
| `updated_at` | `datetime` | Generation timestamp. |

### PositionDetail

Single-position detail view model returned by `PortfolioService.get_position_detail`.

| Field | Type | Description |
|-------|------|-------------|
| `position_id` | `str` | Position identifier. |
| `symbol` | `str` | Trading symbol. |
| `quantity` | `float` | Units held. |
| `cost_price` | `float` | Average cost. |
| `cost_amount` | `float` | Total cost. |
| `current_price` | `float \| None` | Latest price. |
| `market_value` | `float \| None` | Market value. |
| `unrealized_pnl` | `float \| None` | Unrealized PnL. |
| `unrealized_pnl_pct` | `float \| None` | Unrealized PnL percentage. |
| `industry` | `str \| None` | Industry. |
| `health_status` | `PositionHealthStatus` | Health status. |
| `thesis` | `PositionThesis \| None` | Latest thesis. |
| `trade_history` | `list[dict[str, Any]]` | Historical trades for the symbol. |
| `weight` | `float \| None` | Portfolio weight. |
| `updated_at` | `datetime` | Generation timestamp. |

### PortfolioService

Facade that wires repositories, importer, cost calculator, and risk engine together.

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `__init__` | `cost_calculator=None, risk_engine=None, repository=None` | `PortfolioService` | Initializes dependencies; defaults to `MemoryPortfolioRepository`, `CostCalculator`, and `PortfolioRiskEngine`. |
| `create_portfolio` | `user_id: str, name: str, cash: float = 0.0` | `Portfolio` | Creates a portfolio with a generated id and persists it. |
| `get_portfolio` | `portfolio_id: str` | `Portfolio` | Retrieves a portfolio; raises `KeyError` if missing. |
| `list_portfolios` | — | `list[Portfolio]` | Lists all portfolios in creation order. |
| `add_trade` | `portfolio_id, symbol, side, quantity, price, traded_at, fee=0.0, tax=0.0, note=None` | `Trade` | Validates and appends a manual trade, updating cash. |
| `import_csv` | `portfolio_id: str, content: str, field_mapping=None` | `tuple[list[Trade], ImportRecord]` | Imports trades from CSV string content and appends them. |
| `import_csv_file` | `portfolio_id: str, file_path: str, field_mapping=None` | `tuple[list[Trade], ImportRecord]` | Imports trades from a CSV file path. |
| `get_trades` | `portfolio_id: str` | `list[Trade]` | Returns all trades for a portfolio. |
| `get_positions` | `portfolio_id: str, current_prices=None` | `list[Position]` | Derives positions from trades and attaches the latest thesis. |
| `get_risk` | `portfolio_id, current_prices=None, prices_history=None, upcoming_events=None` | `PortfolioRiskReport` | Computes the portfolio risk report. |
| `get_overview` | `portfolio_id, current_prices=None, prices_history=None, upcoming_events=None` | `PortfolioOverview` | Builds the dashboard overview. |
| `get_position_detail` | `portfolio_id, position_id, current_prices=None` | `PositionDetail` | Builds detail view for one position including trade history and weight. |
| `update_thesis` | `portfolio_id, position_id, thesis, entry_conditions=None, hold_conditions=None, invalidation_conditions=None, target_horizon=None, next_review_at=None, status=ThesisStatus.THESIS_VALID` | `PositionThesis` | Creates a new immutable thesis version. |
| `get_thesis_history` | `portfolio_id, position_id` | `list[PositionThesis]` | Returns all thesis versions for a position. |
| `importer` | — | `TradeImporter` | Read-only access to the internal importer (for broker plugin registration). |
| `_ensure_portfolio` | `portfolio_id: str` | `None` | Validates portfolio existence; raises `KeyError` if missing. |
| `_append_trades` | `portfolio_id: str, trades: list[Trade]` | `None` | Persists trades and applies cash delta. |
| `_apply_cash_delta` | `portfolio_id: str, trades: list[Trade]` | `None` | Adjusts portfolio cash by the net cash impact of the trades. |

`_cash_delta(trade)` is a module-level helper that returns the signed cash impact: negative for buys, positive for sells/dividends.

---

## Repositories

### PortfolioRepository Protocol

Contract consumed by `PortfolioService`. All methods operate on domain objects.

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `add_portfolio` | `portfolio: Portfolio` | `None` | Persist a new portfolio. |
| `get_portfolio` | `portfolio_id: str` | `Portfolio \| None` | Retrieve by id. |
| `list_portfolios` | — | `list[Portfolio]` | Return all portfolios ordered by creation time. |
| `update_portfolio` | `portfolio: Portfolio` | `None` | Persist changes to an existing portfolio. |
| `add_trades` | `trades: list[Trade]` | `None` | Persist a batch of trades. |
| `list_trades` | `portfolio_id: str` | `list[Trade]` | Return trades ordered by execution time. |
| `add_thesis` | `portfolio_id: str, thesis: PositionThesis` | `None` | Persist a thesis version. |
| `list_theses` | `portfolio_id: str, position_id=None` | `list[PositionThesis]` | Return thesis versions sorted by position and version. |

### MemoryPortfolioRepository

In-memory implementation backed by dictionaries. Used for unit tests and embedded usage.

Implements all protocol methods. Raises `ValueError` on duplicate portfolio insertion and `KeyError` when a portfolio is not found.

### SQLAlchemyPortfolioRepository

PostgreSQL implementation using short SQLAlchemy sessions.

| Method | Notes |
|--------|-------|
| `add_portfolio` | Inserts a `PortfolioRow`. |
| `get_portfolio` | Loads by primary key and maps to domain. |
| `list_portfolios` | Orders by `created_at`, `portfolio_id`. |
| `update_portfolio` | Updates `user_id`, `name`, and `cash`. |
| `add_trades` | Bulk inserts `TradeRow` records. |
| `list_trades` | Filters by `portfolio_id` and orders by `traded_at`, `trade_id`. |
| `add_thesis` | Inserts a `PositionThesisRow`. |
| `list_theses` | Filters by optional `position_id` and orders by position/version. |

Private mapper functions `_portfolio_to_row`, `_portfolio_from_row`, `_trade_to_row`, `_trade_from_row`, `_thesis_to_row`, and `_thesis_from_row` convert between domain objects and ORM rows.

---

## Cost Engine

### CostCalculator

Computes position cost basis and realized PnL from a sequence of trades using the moving weighted average method (common for A-shares).

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `calculate` | `portfolio_id: str, trades: list[Trade], current_prices=None` | `list[Position]` | Derives current positions with quantity > 0. Computes market value and unrealized PnL when prices are supplied; otherwise marks missing data as `DATA_MISSING`. |
| `calculate_realized_pnl` | `trades: list[Trade]` | `dict[str, float]` | Returns realized PnL per symbol for symbols with non-zero realized PnL. |

### _CostTracker (internal)

Per-symbol cost accumulator used by `CostCalculator`.

| Attribute | Type | Description |
|-----------|------|-------------|
| `symbol` | `str` | Trading symbol. |
| `quantity` | `float` | Current holding quantity. |
| `cost_amount` | `float` | Total cost amount. |
| `realized_pnl` | `float` | Accumulated realized PnL. |
| `trade_count` | `int` | Number of applied trades. |

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `cost_price` | — | `float` | Moving weighted average cost; `0.0` when quantity <= 0. |
| `apply` | `trade: Trade` | `None` | Updates state by side: buy increases quantity/cost, sell transfers cost and realizes PnL, dividend adds realized PnL, split scales quantity. |

---

## Risk Engine

### PortfolioRiskReport and RiskMetric

`RiskMetric` represents a single computed risk metric.

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Metric identifier. |
| `value` | `float` | Computed value. |
| `threshold` | `float \| None` | Limit for comparison. |
| `breached` | `bool` | Whether `value` exceeds `threshold`. |
| `details` | `dict[str, Any]` | Additional context. |

`PortfolioRiskReport` aggregates metrics for a portfolio.

| Field | Type | Description |
|-------|------|-------------|
| `portfolio_id` | `str` | Portfolio identifier. |
| `total_value` | `float` | Total market value of long positions. |
| `metrics` | `list[RiskMetric]` | Computed metrics. |
| `computed_at` | `datetime` | Report timestamp. |
| `max_single_position` | `float` | Threshold for single-position weight. |
| `max_industry_exposure` | `float` | Threshold for industry exposure. |

Properties:

- `has_breach` — `True` if any metric is breached.
- `breached_metrics` — List of breached metrics.

### PortfolioRiskEngine

Computes portfolio risk across eight dimensions.

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `__init__` | `max_single_position=0.05, max_industry_exposure=0.20` | `PortfolioRiskEngine` | Sets threshold defaults. |
| `calculate` | `portfolio_id, positions, prices_history=None, upcoming_events=None` | `PortfolioRiskReport` | Computes the full risk report. Falls back to a data-missing metric when market values are unavailable. |

Risk dimensions implemented as private methods:

| Dimension | Method | Description |
|-----------|--------|-------------|
| 1. Single position | `_single_position_risk` | Maximum position weight versus `max_single_position`. |
| 2. Industry concentration | `_industry_concentration` | Largest industry weight versus `max_industry_exposure`. |
| 3. Style exposure | `_style_exposure` | Simplified growth/value split based on price-to-cost ratio. |
| 4. Correlation | `_correlation_risk` | Proxy via industry clustering. |
| 5. Liquidity | `_liquidity_risk` | Proxy based on largest position value. |
| 6. Volatility | `_volatility` | Position-weighted daily return standard deviation; skipped if no price history. |
| 7. Drawdown | `_drawdown` | Position-weighted maximum drawdown; skipped if no price history. |
| 8. Event concentration | `_event_concentration` | Share of positions with events within 30 days. |

---

## Importer

### BrokerImportPlugin

Abstract broker export file adapter. Implementations parse file formats only and must not store passwords or connect to broker accounts.

| Abstract Member | Type | Description |
|-----------------|------|-------------|
| `name` | `str` | Plugin identifier, e.g. `htsc`. |
| `supported_extensions` | `list[str]` | Supported file extensions. |
| `parse` | `(file_path: Path) -> list[dict[str, Any]]` | Parses a broker file into raw trade rows. |

### TradeImporter

Handles manual entry, CSV/Excel import, broker plugin import, and audit records.

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `__init__` | — | `TradeImporter` | Initializes empty records, counter, and plugin registry. |
| `register_broker_plugin` | `plugin: BrokerImportPlugin` | `None` | Registers a broker adapter. |
| `add_trade_manual` | `portfolio_id, symbol, side, quantity, price, traded_at, fee=0.0, tax=0.0, note=None` | `Trade` | Creates a validated manual trade and records the import. |
| `import_csv` | `portfolio_id, file_path: Path, field_mapping=None` | `tuple[list[Trade], ImportRecord]` | Imports from a CSV file. |
| `import_csv_bytes` | `portfolio_id, content: str, field_mapping=None` | `tuple[list[Trade], ImportRecord]` | Imports from CSV string content. |
| `import_excel` | `portfolio_id, file_path: Path, field_mapping=None` | `tuple[list[Trade], ImportRecord]` | Imports from an Excel file using pandas. |
| `import_broker` | `portfolio_id, file_path: Path, plugin_name: str, field_mapping=None` | `tuple[list[Trade], ImportRecord]` | Imports via a registered broker plugin. |
| `_process_rows` | `portfolio_id, raw_rows, mapping, source, file_name=None` | `tuple[list[Trade], ImportRecord]` | Maps, validates, and creates trades; raises `ImportValidationError` on any row error. |
| `_row_to_trade` | `portfolio_id, row, source, raw_hash=None` | `Trade` | Converts a mapped row into a validated `Trade`. |
| `_record_import` | `portfolio_id, source, trade_count, rejected_count, file_name=None, raw_hash=None, errors=None` | `ImportRecord` | Creates and stores an audit record. |
| `import_records` | — | `list[ImportRecord]` | Read-only access to all import audit records. |

### Validation Helpers

| Function/Exception | Description |
|--------------------|-------------|
| `validate_trade_fields(symbol, side, quantity, price, traded_at)` | Validates that symbol is non-empty, side is a valid `TradeSide`, quantity/price are positive, and `traded_at` is not in the future. Raises `TradeValidationError`. |
| `compute_raw_hash(rows)` | Returns a SHA256 hash string (`sha256:<hex>`) of raw import rows. |
| `ImportValidationError` | Raised when an import file fails validation. Carries `errors` and the associated `record`. |
| `TradeValidationError` | Raised when a single trade record fails validation. |
| `_apply_mapping(row, mapping)` | Maps raw row keys to canonical field names. |
| `_parse_datetime(value)` | Parses dates in several common formats (`%Y-%m-%d`, `%Y/%m/%d`, etc.). |

Default CSV field mapping (`_DEFAULT_CSV_MAPPING`) maps `symbol`, `side`, `quantity`, `price`, `traded_at`, `fee`, `tax`, and `note` to themselves.

---

## FastAPI Endpoints

All routes are registered under `/api/v1` via `APIRouter(prefix="/api/v1", tags=["portfolio"])`.

| Method | Path | Summary | Request | Response |
|--------|------|---------|---------|----------|
| `GET` | `/portfolios/{portfolio_id}` | Return portfolio identity and dashboard overview. | Path: `portfolio_id` | `PortfolioDashboardResponse` |
| `GET` | `/portfolios/{portfolio_id}/positions` | Return current positions. | Path: `portfolio_id` | `list[Position]` |
| `GET` | `/portfolios/{portfolio_id}/positions/{position_id}` | Return single position detail with thesis and trade history. | Path: `portfolio_id`, `position_id` | `PositionDetail` |
| `POST` | `/portfolios/{portfolio_id}/trades` | Append a manually entered trade. | `TradeCreate` body | `Trade` (201) |
| `POST` | `/portfolios/{portfolio_id}/imports` | Import trades from CSV content atomically. | `CSVImportRequest` body | `CSVImportResponse` (201) |
| `GET` | `/portfolios/{portfolio_id}/risk` | Return portfolio risk report. | Path: `portfolio_id` | `PortfolioRiskReport` |
| `GET` | `/positions/{position_id}/thesis` | Return latest thesis for a position. | Query: `portfolio_id` | `PositionThesis` |
| `PUT` | `/positions/{position_id}/thesis` | Create a new immutable thesis version. | `ThesisUpdate` body | `PositionThesis` |

Error handling:

- `KeyError` raised by the service is converted to HTTP `404 Not Found`.
- `TradeValidationError` results in HTTP `422 Unprocessable Content`.
- `ImportValidationError` results in HTTP `422` with message, per-row errors, and the failed import record.

### Request/Response Schemas

Defined in `/Users/wangruiqi/PycharmProjects/Margin/src/margin/api/schemas.py`:

| Schema | Purpose |
|--------|---------|
| `TradeCreate` | Validates manual trade requests. |
| `CSVImportRequest` | Validates CSV content and optional field mapping. |
| `CSVImportResponse` | Wraps imported trades and the import record. |
| `ThesisUpdate` | Validates thesis creation/update requests. |
| `PortfolioDashboardResponse` | Combines `Portfolio` identity and `PortfolioOverview`. |

---

## React Page and Component

### PortfolioPage

`PortfolioPage` is an async Next.js server component at `/app/portfolios/[portfolioId]/page.tsx`.

| Prop | Type | Description |
|------|------|-------------|
| `params` | `Promise<{ portfolioId: string }>` | Next.js route parameters. |

Behavior:

1. Awaits `params` and extracts `portfolioId`.
2. Fetches `PortfolioDashboard` and `Position[]` in parallel via `fetchPortfolioDashboard(portfolioId)` and `fetchPortfolioPositions(portfolioId)` from `/Users/wangruiqi/PycharmProjects/Margin/web/lib/api.ts`.
3. On error, sets a localized error message (`组合数据暂时不可用`).
4. Renders `PortfolioWorkspace` with `dashboard`, `positions`, and `error`.

### PortfolioWorkspace

`PortfolioWorkspace` is a client component in `/Users/wangruiqi/PycharmProjects/Margin/web/components/portfolio-workspace.tsx`.

| Prop | Type | Description |
|------|------|-------------|
| `dashboard` | `PortfolioDashboard \| null` | Portfolio identity and overview data. |
| `positions` | `Position[]` | Current positions. |
| `error` | `string \| null` | Error message. |

Behavior:

- If `error` is present, renders an alert panel.
- If `dashboard` is null, renders a loading notice.
- Otherwise renders:
  - Header with portfolio name, position count, and high-risk count.
  - Metric tiles for total assets, cash, market value, and cumulative PnL.
  - Positions table with columns symbol, quantity, cost, market value, PnL, and health status. Each symbol links to `/positions/{position_id}?portfolioId={portfolio_id}`.
  - Empty state (`暂无持仓`) when no positions exist.
  - Side rail with industry exposure, style exposure, upcoming events, volatility, and drawdown.

Helper functions inside the component:

| Helper | Purpose |
|--------|---------|
| `money(value)` | Formats a number as CNY currency or `--`. |
| `ratio(value)` | Formats a number as a percentage or `--`. |
| `signedMoney(value)` | Formats a signed CNY amount. |
| `metricTone(value)` | Returns `positive`, `negative`, or `neutral` based on value sign. |
| `MetricTile` | Renders a single metric card. |
| `ExposurePanel` | Renders an exposure list with percentage labels and `<meter>` bars. |

---

## Cross-Module Usage Notes

- **Dependency injection**: `PortfolioService` is provided to FastAPI route handlers via `get_portfolio_service` in `/Users/wangruiqi/PycharmProjects/Margin/src/margin/api/dependencies.py`. This lets the API use a single service instance (often backed by `SQLAlchemyPortfolioRepository`) across requests.
- **Holdings monitoring (module 09)**: The monitoring module consumes domain types defined here (`Position`, `PositionThesis`, `ThesisStatus`, `Trade`, `AlertEvent`) and evaluates position health, thesis status, and alerts. It does not own the trade or portfolio storage.
- **Research candidate dashboard (module 08)**: Portfolio context such as current positions and constraints can be supplied to research runs; the research module reads portfolio data through the API rather than writing to holdings storage.
- **Position detail page**: `/web/app/positions/[positionId]/page.tsx` calls `fetchPositionDetail(portfolioId, positionId)`, which hits the portfolio detail endpoint defined in this module.
- **Cash synchronization**: `PortfolioService.add_trade` and import methods update the portfolio `cash` balance immediately via `_apply_cash_delta`, keeping cash consistent with recorded trades.
- **Immutability and versioning**: Trades and thesis versions are append-only. Updating a thesis creates a new `PositionThesis` row with an incremented version, preserving history.
