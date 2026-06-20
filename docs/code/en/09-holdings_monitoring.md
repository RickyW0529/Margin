# Module 09 — Holdings Monitoring

Complete function-level documentation for the `09-holdings_monitoring` module of the current Margin implementation.

## Table of Contents

- [1. Module Overview](#1-module-overview)
- [2. File-Level Summaries](#2-file-level-summaries)
- [3. Domain Models](#3-domain-models)
  - [3.1 Enums](#31-enums)
  - [3.2 AlertEvent](#32-alertevent)
  - [3.3 PositionMonitoringSnapshot](#33-positionmonitoringsnapshot)
  - [3.4 PositionReviewRecord](#34-positionreviewrecord)
  - [3.5 OperationHistoryEntry](#35-operationhistoryentry)
  - [3.6 BehaviorMetric](#36-behaviormetric)
- [4. Service Layer](#4-service-layer)
  - [4.1 HoldingsMonitoringService](#41-holdingsmonitoringservice)
  - [4.2 MonitoringServiceBundle](#42-monitoringservicebundle)
- [5. Runner and Providers](#5-runner-and-providers)
  - [5.1 Protocols](#51-protocols)
  - [5.2 AKShareLatestPriceProvider](#52-aksharelatestpriceprovider)
  - [5.3 RepositoryNewsEventProvider](#53-repositorynewseventprovider)
  - [5.4 LoggingNotificationSink](#54-loggingnotificationsink)
  - [5.5 HoldingsMonitoringRunner](#55-holdingsmonitoringrunner)
- [6. Repository Layer](#6-repository-layer)
  - [6.1 MonitoringRepository Protocol](#61-monitoringrepository-protocol)
  - [6.2 MemoryMonitoringRepository](#62-memorymonitoringrepository)
  - [6.3 SQLAlchemyMonitoringRepository](#63-sqlalchemymonitoringrepository)
- [7. FastAPI Endpoints](#7-fastapi-endpoints)
- [8. Next.js Page and Server Actions](#8-nextjs-page-and-server-actions)
- [9. React Components](#9-react-components)
  - [9.1 PositionDetailView](#91-positiondetailview)
  - [9.2 PositionReviewBadge](#92-positionreviewbadge)
- [10. Cross-Module Usage Notes](#10-cross-module-usage-notes)

---

## 1. Module Overview

The `holdings_monitoring` module (module 09) is responsible for continuously evaluating open positions against deterministic rules, surfacing alerts when a position's investment thesis is at risk, and recording manual reviews that capture the portfolio manager's response.

Key responsibilities:

- Evaluate each position for price-based invalidation, scheduled review dates, strategy failures, model rank changes, industry exposure limits, and upcoming key events.
- Scan recent document events from the news module and emit negative-event or new-disclosure alerts when event text matches a Chinese negative-term lexicon.
- Persist alert events and manual review records append-only.
- Build a unified operation history per position by merging trades, alerts, and reviews.
- Compute lightweight behavior metrics (alert-to-review latency) for post-hoc analysis.
- Expose the functionality through FastAPI routes consumed by the Next.js position detail page.

The module is intentionally deterministic and intraday-safe: it does not perform LLM calls during the evaluation path. It can be run on-demand through the API or swept automatically via `HoldingsMonitoringRunner`.

---

## 2. File-Level Summaries

| File | Purpose |
|------|---------|
| `src/margin/holdings_monitoring/__init__.py` | Public package exports. Re-exports models, repositories, and services. |
| `src/margin/holdings_monitoring/db_models.py` | SQLAlchemy ORM rows `AlertEventRow` and `PositionReviewRow` with indexes. |
| `src/margin/holdings_monitoring/models.py` | Pydantic domain models and enums: `AlertEvent`, `PositionMonitoringSnapshot`, `PositionReviewRecord`, `OperationHistoryEntry`, `BehaviorMetric`. |
| `src/margin/holdings_monitoring/repository.py` | `MonitoringRepository` protocol plus `MemoryMonitoringRepository` and `SQLAlchemyMonitoringRepository` implementations. |
| `src/margin/holdings_monitoring/runner.py` | `HoldingsMonitoringRunner` and adapter protocols/providers for prices, news, and notifications. |
| `src/margin/holdings_monitoring/service.py` | Core `HoldingsMonitoringService` with rule engine, plus `MonitoringServiceBundle` for dependency injection. |
| `src/margin/api/routes/monitoring.py` | FastAPI router exposing evaluation, alerts, reviews, history, and behavior metrics endpoints. |
| `web/app/positions/[positionId]/page.tsx` | Next.js server component that loads position detail, alerts, and history. |
| `web/app/positions/[positionId]/loading.tsx` | Loading UI for the position detail page. |
| `web/app/positions/[positionId]/actions.ts` | Server actions that bind form submissions to the monitoring and review API endpoints. |
| `web/components/position-detail.tsx` | Main React component rendering the position detail view, monitoring panel, review form, and operation history. |
| `web/components/position-detail.test.tsx` | Vitest tests for `PositionDetailView`. |
| `web/components/position-review-badge.tsx` | Small badge component mapping thesis status to a localized label and tone. |

---

## 3. Domain Models

### 3.1 Enums

| Enum | Values | Description |
|------|--------|-------------|
| `AlertPriority` | `P0`, `P1`, `P2`, `P3` | Priority levels defined by product design. `P0` is the highest. |
| `AlertType` | `data_quality`, `new_disclosure`, `negative_event`, `price_invalidation`, `model_rank_change`, `industry_exposure`, `valuation_target`, `strategy_failure`, `key_event_pending` | Supported deterministic alert categories. |
| `ReviewDecision` | `hold`, `reduce`, `exit`, `watch`, `ignore` | Manual review decisions recorded after an alert. |

### 3.2 AlertEvent

`class AlertEvent(BaseModel)` — Append-only alert emitted by the monitoring rule engine.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `alert_id` | `str` | `al_<uuid[:12]>` | Unique alert identifier. |
| `portfolio_id` | `str` | required | Owning portfolio. |
| `position_id` | `str` | required | Target position. |
| `symbol` | `str` | required | Ticker symbol. |
| `alert_type` | `AlertType` | required | Alert category. |
| `severity` | `AlertPriority` | `P2` | Priority. |
| `message` | `str` | required | Human-readable description. |
| `rule_name` | `str` | required | Rule that emitted the alert; used for cooldown de-duplication. |
| `triggered_at` | `datetime` | `utc_now()` | Timestamp when the alert was triggered. |
| `evidence_refs` | `list[str]` | `[]` | References to evidence or events. |
| `changed_thesis` | `bool` | `False` | Whether the alert invalidates the investment thesis. |
| `acknowledged_at` | `datetime \| None` | `None` | Optional acknowledgement timestamp. |

| Method | Description |
|--------|-------------|
| `normalize_timestamps(value)` | Field validator ensuring `triggered_at` and `acknowledged_at` are UTC. |

### 3.3 PositionMonitoringSnapshot

`class PositionMonitoringSnapshot(BaseModel)` — Result of one deterministic position monitoring evaluation.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `position_id` | `str` | required | Target position. |
| `portfolio_id` | `str` | required | Owning portfolio. |
| `symbol` | `str` | required | Ticker symbol. |
| `health_status` | `PositionHealthStatus` | required | Derived health status. |
| `thesis_status` | `ThesisStatus` | required | Derived thesis status. |
| `evaluated_at` | `datetime` | `utc_now()` | Evaluation timestamp. |
| `reasons` | `list[str]` | `[]` | Human-readable reason strings. |
| `alerts` | `list[AlertEvent]` | `[]` | Alerts emitted after cooldown filtering. |
| `data_missing` | `bool` | `False` | True when price data is missing. |

| Method | Description |
|--------|-------------|
| `normalize_evaluated_at(value)` | Field validator ensuring `evaluated_at` is UTC. |

### 3.4 PositionReviewRecord

`class PositionReviewRecord(BaseModel)` — Append-only manual review record after an alert.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `review_id` | `str` | `rv_<uuid[:12]>` | Unique review identifier. |
| `portfolio_id` | `str` | required | Owning portfolio. |
| `position_id` | `str` | required | Target position. |
| `alert_id` | `str \| None` | `None` | Optional linked alert. |
| `decision` | `ReviewDecision` | required | Manager decision. |
| `rationale` | `str` | required | Free-text rationale. |
| `action_taken_at` | `datetime \| None` | `None` | When the action was executed. |
| `created_at` | `datetime` | `utc_now()` | Record creation time. |

| Method | Description |
|--------|-------------|
| `normalize_review_timestamps(value)` | Field validator ensuring `action_taken_at` and `created_at` are UTC. |

### 3.5 OperationHistoryEntry

`class OperationHistoryEntry(BaseModel)` — Unified operation-history entry for the position detail view.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `event_id` | `str` | required | Trade, alert, or review identifier. |
| `position_id` | `str` | required | Target position. |
| `event_type` | `str` | required | `"trade"`, `"alert"`, or `"review"`. |
| `occurred_at` | `datetime` | required | Event timestamp. |
| `summary` | `str` | required | Short human-readable summary. |
| `metadata` | `dict[str, Any]` | `{}` | Additional structured metadata. |

| Method | Description |
|--------|-------------|
| `normalize_occurred_at(value)` | Field validator ensuring `occurred_at` is UTC. |

### 3.6 BehaviorMetric

`class BehaviorMetric(BaseModel)` — User behavior metric derived from alert and review timestamps.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `metric_id` | `str` | `bm_<uuid[:12]>` | Unique metric identifier. |
| `portfolio_id` | `str` | required | Owning portfolio. |
| `position_id` | `str` | required | Target position. |
| `alert_id` | `str` | required | Source alert. |
| `review_id` | `str` | required | Source review. |
| `action_latency_seconds` | `int \| None` | `None` | Seconds between alert trigger and review action. |
| `signal_execution_gap` | `str \| None` | `None` | Review decision value; records what action was taken. |

---

## 4. Service Layer

### 4.1 HoldingsMonitoringService

`class HoldingsMonitoringService` — Deterministic holdings monitoring service for intraday-safe checks.

| Constant | Value | Meaning |
|----------|-------|---------|
| `PRICE_INVALIDATION_DRAWDOWN` | `0.10` | Price drop that invalidates the thesis (P0). |
| `PRICE_RISK_DRAWDOWN` | `0.05` | Price drop that triggers a risk alert (P1). |
| `ALERT_COOLDOWN` | `timedelta(hours=6)` | Minimum interval before the same rule emits again. |

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `__init__` | `repository: MonitoringRepository \| None = None`, `portfolio_service: PortfolioService \| None = None` | — | Creates the service. Defaults to `MemoryMonitoringRepository`. |
| `evaluate_position` | `portfolio_id: str`, `position: Position`, `thesis: PositionThesis \| None`, `current_price: float \| None = None`, `evidence_refs: list[str] \| None = None`, `model_rank_delta: float \| None = None`, `industry_exposure: float \| None = None`, `strategy_failure: bool = False`, `upcoming_event_at: datetime \| None = None`, `news_events: list[DocumentEvent] \| None = None`, `decision_at: datetime \| None = None` | `PositionMonitoringSnapshot` | Runs all deterministic rules for a single position. Emits and persists alerts after cooldown filtering. |
| `evaluate_position_by_id` | `portfolio_id: str`, `position_id: str`, plus optional evaluation inputs | `PositionMonitoringSnapshot` | Loads the position detail from `PortfolioService` and delegates to `evaluate_position`. Raises `RuntimeError` if no portfolio service is configured. |
| `list_alerts` | `portfolio_id: str`, `position_id: str \| None = None` | `list[AlertEvent]` | Returns persisted alerts, optionally filtered by position. |
| `record_review` | `portfolio_id: str`, `position_id: str`, `alert_id: str \| None`, `decision: ReviewDecision`, `rationale: str`, `action_taken_at: datetime \| None = None` | `PositionReviewRecord` | Validates the alert if provided, creates a review record, and persists it. |
| `list_reviews` | `portfolio_id: str`, `position_id: str \| None = None` | `list[PositionReviewRecord]` | Returns persisted reviews, optionally filtered by position. |
| `get_behavior_metrics` | `portfolio_id: str`, `position_id: str` | `list[BehaviorMetric]` | Joins alerts to reviews and computes action latency. |
| `get_operation_history` | `portfolio_id: str`, `position_id: str`, `trades: list[Trade] \| None = None` | `list[OperationHistoryEntry]` | Merges trades, alerts, and reviews into a sorted timeline. Loads trades from `PortfolioService` when not supplied. |
| `_build_alert` | position, alert type, severity, rule name, message, timestamp, evidence, changed thesis flag | `AlertEvent` | Internal factory for creating alert events. |

Evaluation rules applied by `evaluate_position`:

1. **Missing price data** — if `current_price` and `position.current_price` are both `None`, status becomes `DATA_MISSING`, emits `data_quality` P2 alert.
2. **Price invalidation** — price <= cost price * 0.90: status `INVALIDATED`, thesis `THESIS_INVALIDATED`, emits `price_invalidation` P0 alert with `changed_thesis=True`.
3. **Price risk** — price <= cost price * 0.95: status `RISK`, thesis `RISK_ALERT`, emits `price_invalidation` P1 alert.
4. **Scheduled review due** — if `thesis.next_review_at` has passed: status `EVENT_PENDING`, emits `key_event_pending` P2 alert.
5. **Strategy failure** — if `strategy_failure=True`: status `WATCH`, emits `strategy_failure` P2 alert.
6. **Model rank drop** — if `model_rank_delta <= -30`: status `WATCH`, emits `model_rank_change` P2 alert.
7. **Industry exposure** — if `industry_exposure >= 0.35`: status `WATCH`, emits `industry_exposure` P2 alert.
8. **Upcoming key event** — if `upcoming_event_at` is provided: status `EVENT_PENDING`, emits `key_event_pending` P2 alert.
9. **News events** — for each recent `DocumentEvent` affecting the symbol, checks a Chinese negative-term lexicon. Negative events that can change research state trigger `negative_event` P1 alerts with `changed_thesis=True`; other events trigger `new_disclosure` P2 alerts.

After all rules run, alerts are de-duplicated using `ALERT_COOLDOWN` per `(portfolio_id, position_id, rule_name)`. Only alerts outside the cooldown window are persisted and returned in the snapshot.

### 4.2 MonitoringServiceBundle

`@dataclass(frozen=True) class MonitoringServiceBundle` — Container for FastAPI dependency injection.

| Field | Type | Description |
|-------|------|-------------|
| `monitoring` | `HoldingsMonitoringService` | The monitoring service instance. |

| Class Method | Parameters | Returns | Description |
|--------------|------------|---------|-------------|
| `in_memory` | `portfolio_service: PortfolioService \| None = None`, `repository: MemoryMonitoringRepository \| None = None` | `MonitoringServiceBundle` | Factory using an in-memory repository. |
| `from_repositories` | `repository: MonitoringRepository`, `portfolio_service: PortfolioService` | `MonitoringServiceBundle` | Factory using a provided repository and portfolio service. |

---

## 5. Runner and Providers

### 5.1 Protocols

| Protocol | Method | Description |
|----------|--------|-------------|
| `LatestPriceProvider` | `get_latest_prices(symbols: list[str], *, as_of: datetime) -> dict[str, float]` | Resolves latest prices for a batch of symbols. |
| `NotificationSink` | `notify(alert: AlertEvent) -> None` | Delivers high-priority alerts. |
| `NewsEventProvider` | `get_recent_events(symbols: list[str], *, since: datetime, as_of: datetime) -> list[DocumentEvent]` | Resolves recent document events for held symbols. |

### 5.2 AKShareLatestPriceProvider

`class AKShareLatestPriceProvider` — Latest-price adapter using adjusted daily bars from AKShare.

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `__init__` | `provider: AKShareProvider \| None = None` | — | Creates or accepts an `AKShareProvider`. |
| `get_latest_prices` | `symbols: list[str]`, `as_of: datetime` | `dict[str, float]` | Fetches bars for the previous 14 days and returns the most recent close per symbol. Returns `{}` on empty input or provider failure. |

### 5.3 RepositoryNewsEventProvider

`class RepositoryNewsEventProvider` — Reads the module 03 document-event stream for holdings monitoring.

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `__init__` | `repository: NewsRepository` | — | Binds a `NewsRepository`. |
| `get_recent_events` | `symbols: list[str]`, `since: datetime`, `as_of: datetime` | `list[DocumentEvent]` | Filters `list_unique_events()` to events whose symbols overlap the requested set and whose `available_at` falls within `(since, as_of]`. |

### 5.4 LoggingNotificationSink

`class LoggingNotificationSink` — Local-first notification sink backed by structured application logs.

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `notify` | `alert: AlertEvent` | `None` | Logs a warning with structured fields: `alert_id`, `portfolio_id`, `position_id`, `symbol`, `severity`, `rule_name`. |

### 5.5 HoldingsMonitoringRunner

`class HoldingsMonitoringRunner` — Evaluate every persisted position using current market prices.

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `__init__` | `portfolio_service: PortfolioService`, `monitoring_service: HoldingsMonitoringService`, `price_provider: LatestPriceProvider`, `news_provider: NewsEventProvider \| None = None`, `notifier: NotificationSink \| None = None` | — | Wires up services and adapters. Defaults to `LoggingNotificationSink`. |
| `run_once` | `decision_at: datetime \| None = None` | `list[PositionMonitoringSnapshot]` | Iterates over all portfolios, fetches positions, prices, and recent news, evaluates every position, and notifies for P0/P1 alerts. Updates `_last_news_check` after completion. |

---

## 6. Repository Layer

### 6.1 MonitoringRepository Protocol

`class MonitoringRepository(Protocol)` — Persistence contract consumed by holdings monitoring services.

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `add_alert` | `alert: AlertEvent` | `None` | Append an alert event. |
| `list_alerts` | `portfolio_id: str`, `position_id: str \| None = None` | `list[AlertEvent]` | Return alerts for a portfolio, optionally filtered by position. |
| `get_alert` | `alert_id: str` | `AlertEvent \| None` | Return one alert by identifier. |
| `get_latest_alert` | `portfolio_id: str`, `position_id: str`, `rule_name: str` | `AlertEvent \| None` | Return the latest alert emitted by one monitoring rule. |
| `add_review` | `review: PositionReviewRecord` | `None` | Append a manual position review. |
| `list_reviews` | `portfolio_id: str`, `position_id: str \| None = None` | `list[PositionReviewRecord]` | Return review records for a portfolio or position. |

### 6.2 MemoryMonitoringRepository

`class MemoryMonitoringRepository` — In-memory monitoring repository for tests and embedded usage.

Stores alerts and reviews in private dictionaries keyed by ID. All list methods sort results by timestamp and then ID.

| Method | Description |
|--------|-------------|
| `__init__` | Initializes empty `_alerts` and `_reviews` dicts. |
| `add_alert(alert)` | Stores alert by `alert_id`. |
| `list_alerts(...)` | Filters by portfolio and optional position, sorted by `(triggered_at, alert_id)`. |
| `get_alert(alert_id)` | Dict lookup. |
| `get_latest_alert(...)` | Finds max by `triggered_at`. |
| `add_review(review)` | Stores review by `review_id`. |
| `list_reviews(...)` | Filters by portfolio and optional position, sorted by `(created_at, review_id)`. |

### 6.3 SQLAlchemyMonitoringRepository

`class SQLAlchemyMonitoringRepository` — PostgreSQL monitoring repository backed by short SQLAlchemy sessions.

| Method | Parameters | Description |
|--------|------------|-------------|
| `__init__` | `session_factory: Callable[[], Session]` | Stores the session factory. |
| `add_alert` | `alert: AlertEvent` | Converts to `AlertEventRow` and inserts in a transaction. |
| `list_alerts` | `portfolio_id`, optional `position_id` | Queries `AlertEventRow` ordered by `triggered_at`, `alert_id`. |
| `get_alert` | `alert_id` | Loads `AlertEventRow` by primary key. |
| `get_latest_alert` | `portfolio_id`, `position_id`, `rule_name` | Queries descending by `triggered_at` with `limit(1)`. |
| `add_review` | `review: PositionReviewRecord` | Converts to `PositionReviewRow` and inserts in a transaction. |
| `list_reviews` | `portfolio_id`, optional `position_id` | Queries `PositionReviewRow` ordered by `created_at`, `review_id`. |

Private mapping helpers:

| Function | Description |
|----------|-------------|
| `_alert_to_row(alert)` | Converts `AlertEvent` to `AlertEventRow`. |
| `_alert_from_row(row)` | Converts `AlertEventRow` to `AlertEvent`. |
| `_review_to_row(review)` | Converts `PositionReviewRecord` to `PositionReviewRow`. |
| `_review_from_row(row)` | Converts `PositionReviewRow` to `PositionReviewRecord`. |

---

## 7. FastAPI Endpoints

Router: `src/margin/api/routes/monitoring.py`

Prefix: `/api/v1`
Tag: `monitoring`

| Method | Path | Summary | Request | Response |
|--------|------|---------|---------|----------|
| `POST` | `/positions/{position_id}/monitoring/evaluate` | Evaluate a position using deterministic monitoring rules. | `MonitoringEvaluateRequest` body | `PositionMonitoringSnapshot` (201) |
| `GET` | `/positions/{position_id}/alerts` | Return append-only alert events for a position. | Query: `portfolio_id` (required, min length 1) | `list[AlertEvent]` |
| `POST` | `/positions/{position_id}/reviews` | Append a manual review for a position alert. | `ReviewCreate` body | `PositionReviewRecord` (201) |
| `GET` | `/positions/{position_id}/history` | Return unified trade/alert/review operation history. | Query: `portfolio_id` (required, min length 1) | `list[OperationHistoryEntry]` |
| `GET` | `/positions/{position_id}/behavior-metrics` | Return action-latency metrics derived from alert/review records. | Query: `portfolio_id` (required, min length 1) | `list[BehaviorMetric]` |

### Request schemas

`MonitoringEvaluateRequest`:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `portfolio_id` | `str` | yes | Portfolio identifier. |
| `current_price` | `float \| None` | no | Override price; backend price used if omitted. |
| `evidence_refs` | `list[str]` | no | Evidence IDs to attach to emitted alerts. |
| `model_rank_delta` | `float \| None` | no | Model rank change to evaluate. |
| `industry_exposure` | `float \| None` | no | Industry exposure ratio to evaluate. |
| `strategy_failure` | `bool` | no | Flag strategy failure. |
| `upcoming_event_at` | `datetime \| None` | no | Timestamp of an upcoming key event. |
| `decision_at` | `datetime \| None` | no | Evaluation timestamp. |

`ReviewCreate`:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `portfolio_id` | `str` | yes | Portfolio identifier. |
| `alert_id` | `str \| None` | no | Associated alert. |
| `decision` | `ReviewDecision` | yes | Review decision. |
| `rationale` | `str` | yes | Review rationale. |
| `action_taken_at` | `datetime \| None` | no | When action was taken. |

All endpoints inject `MonitoringServiceBundle` via `get_monitoring_services`. `KeyError` exceptions are converted to `HTTP 404`.

---

## 8. Next.js Page and Server Actions

### `PositionPage`

File: `web/app/positions/[positionId]/page.tsx`

Server component for the `/positions/{positionId}` route.

| Prop | Type | Description |
|------|------|-------------|
| `params` | `Promise<{ positionId: string }>` | Next.js route parameters. |
| `searchParams` | `Promise<{ portfolioId?: string }>` | Query string; defaults `portfolioId` to `"demo"`. |

Behavior:

1. Awaits `params` and `searchParams`.
2. Fetches `PositionDetail`, alerts, and operation history in parallel via `Promise.all`.
3. On failure, stores a Chinese error message (`"持仓数据暂时不可用"`).
4. Renders `PositionDetailView` with pre-bound server actions and fetched data.

### Server Actions

File: `web/app/positions/[positionId]/actions.ts`

| Function | Parameters | Description |
|----------|------------|-------------|
| `evaluatePositionAction` | `positionId: string`, `formData: FormData` | Extracts `portfolio_id`, optional numeric fields, checkbox state, and evidence list; calls `evaluatePositionMonitoring`; then `revalidatePath(`/positions/${positionId}`)`. |
| `createPositionReviewAction` | `positionId: string`, `formData: FormData` | Extracts `portfolio_id`, optional `alert_id`, `decision`, and `rationale`; calls `createPositionReview`; then revalidates the page. |

Helper functions in `actions.ts`:

| Function | Description |
|----------|-------------|
| `requiredText(formData, key)` | Returns trimmed text or throws. |
| `optionalText(formData, key)` | Returns trimmed text or `null`. |
| `optionalNumber(formData, key)` | Parses finite number or returns `null`. |
| `splitList(value)` | Splits a string by whitespace/commas/semicolons into a cleaned list. |
| `reviewDecision(formData)` | Validates decision against allowed values; defaults to `"watch"`. |

---

## 9. React Components

### 9.1 PositionDetailView

File: `web/components/position-detail.tsx`

`function PositionDetailView(props: PositionDetailViewProps)` — Main interactive view for a single position.

| Prop | Type | Description |
|------|------|-------------|
| `portfolioId` | `string` | Portfolio identifier shown in the eyebrow. |
| `evaluateAction` | `FormAction` | Bound server action for the monitoring evaluation form. |
| `reviewAction` | `FormAction` | Bound server action for the review form. |
| `detail` | `PositionDetail \| null` | Position detail data. |
| `alerts` | `AlertEvent[]` | Alert list; defaults to `[]`. |
| `history` | `OperationHistoryEntry[]` | Operation history; defaults to `[]`. |
| `error` | `string \| null` | Error message. |

Behavior:

- Renders an error panel when `error` is set.
- Renders a loading placeholder when `detail` is `null`.
- Displays position header with symbol and `health_status` badge.
- Shows metric tiles for cost amount, cost price, market value, and weight.
- Renders the investment thesis with hold and invalidation conditions.
- Renders the monitoring panel: alert list with severity badges, plus `MonitoringEvaluateForm`.
- Renders the review form (`ReviewForm`) in the side rail.
- Renders the operation history timeline (falls back to `tradesToHistory(detail)` if `history` is empty).

Internal components:

| Component | Props | Description |
|-----------|-------|-------------|
| `MonitoringEvaluateForm` | `action`, `portfolioId`, `detail` | Form with inputs for current price, model rank delta, industry exposure, evidence refs, and strategy-failure checkbox. |
| `ReviewForm` | `action`, `portfolioId`, `alerts` | Form to record a review, with dropdowns for linked alert and decision, plus rationale textarea. |
| `Metric` | `label`, `value` | Simple metric tile. |
| `ConditionList` | `title`, `items` | Renders a thesis condition list. |

Helper functions:

| Function | Description |
|----------|-------------|
| `money(value)` | Formats a number as CNY or `"--"`. |
| `ratio(value)` | Formats a number as a percent or `"--"`. |
| `tradesToHistory(detail)` | Converts `trade_history` into `OperationHistoryEntry` objects. |
| `historySummary(entry)` | Returns `"触发提醒"` for alert entries, otherwise `entry.summary`. |

### 9.2 PositionReviewBadge

File: `web/components/position-review-badge.tsx`

`function PositionReviewBadge({ status }: PositionReviewBadgeProps)` — Maps a thesis/review status to a localized badge.

| Prop | Type | Description |
|------|------|-------------|
| `status` | `string \| null` | Thesis status value. |

Behavior:

- If `status` is `null`, renders `"未绑定组合"`.
- Chooses a tone class:
  - `"data_missing"` when status contains `RISK` or `INVALID`.
  - `"watch"` when status contains `REVIEW`.
  - `"positive"` otherwise.
- Maps status to a Chinese label via the `labels` table; falls back to the raw status.

Label mapping:

| Status | Label |
|--------|-------|
| `THESIS_VALID` | `逻辑有效` |
| `REVIEW_REQUIRED` | `需要复核` |
| `RISK_ALERT` | `风险提醒` |
| `THESIS_INVALIDATED` | `逻辑失效` |

---

## 10. Cross-Module Usage Notes

- **Portfolio module (module 05)**: `HoldingsMonitoringService` accepts `PortfolioService` to load position details and trades. `HoldingsMonitoringRunner` iterates portfolios and positions through `PortfolioService`. Position health and thesis statuses are defined in `margin.portfolio.models`.
- **News module (module 03)**: `RepositoryNewsEventProvider` consumes `NewsRepository.list_unique_events()` to supply `DocumentEvent` objects. The service scans event titles and content for Chinese negative terms to emit `negative_event` or `new_disclosure` alerts.
- **Data module (AKShare)**: `AKShareLatestPriceProvider` wraps `AKShareProvider` to fetch daily adjusted bars and resolve the latest close per symbol.
- **Dashboard module (module 08)**: `PositionReviewBadge` can be reused in dashboard candidate cards to render `position_review_status` or `research_status`.
- **API wiring**: `get_monitoring_services` in `src/margin/api/dependencies.py` builds a production `MonitoringServiceBundle` using `SQLAlchemyMonitoringRepository` and `SQLAlchemyPortfolioRepository`, both sharing a database engine.
- **Frontend API client**: `web/lib/api.ts` defines TypeScript types (`AlertEvent`, `OperationHistoryEntry`, `PositionMonitoringSnapshot`, `PositionReviewRecord`, etc.) and fetch helpers (`fetchPositionAlerts`, `fetchPositionHistory`, `evaluatePositionMonitoring`, `createPositionReview`) used by the position page.
