# Module 08: Research Candidate Dashboard

Complete function-level documentation for the `08-research_candidate_dashboard` module of Margin v0.1.

## Table of Contents

1. [Module Overview](#1-module-overview)
2. [File-Level Summaries](#2-file-level-summaries)
3. [Domain Models](#3-domain-models)
4. [Services](#4-services)
5. [Repository](#5-repository)
6. [FastAPI Endpoints](#6-fastapi-endpoints)
7. [Next.js Pages and Server Actions](#7-nextjs-pages-and-server-actions)
8. [React Components](#8-react-components)
9. [Cross-Module Usage Notes](#9-cross-module-usage-notes)

---

## 1. Module Overview

The Research Candidate Dashboard (module 08) is the presentation and interaction layer for research signals produced by the multi-agent research workflow (module 06). It aggregates per-symbol workflow results into dashboard runs and items, exposes them through a FastAPI backend-for-frontend (BFF), and renders them in a Next.js/React user interface.

### Responsibilities

- **Run aggregation**: Collect module 06 workflow outputs into immutable `ResearchRun` and `ResearchItem` aggregates.
- **Candidate presentation**: Derive `CandidateCard` and `HomeSummary` views optimized for the UI home page and run pages.
- **Evidence expansion**: Surface claims, evidence locators, source distribution, and confidence for a single research item.
- **Valuation view**: Extract valuation ranges and risk scores from module 06 snapshot tool outputs.
- **Report rendering**: Generate auditable Markdown/JSON research reports combining summary, valuation, evidence, counter-arguments, and audit metadata.
- **User feedback**: Append-only feedback records (`accept`, `reject`, `watch`, `comment`) attached to research items.
- **Provider health**: Expose status of LLM, embedding, web search, and rerank providers used by the dashboard pipeline.
- **Nightly run jobs**: Provide synchronous MVP job endpoints for triggering dashboard runs.

---

## 2. File-Level Summaries

### Backend

| File | Purpose |
|------|---------|
| `src/margin/dashboard/__init__.py` | Public package exports for models, repositories, and services. |
| `src/margin/dashboard/db_models.py` | SQLAlchemy rows: `DashboardRunRow`, `DashboardItemRow`, `DashboardFeedbackRow`. |
| `src/margin/dashboard/models.py` | Pydantic domain models, enums, and read-only view models. |
| `src/margin/dashboard/repository.py` | Repository protocol and in-memory/PostgreSQL implementations. |
| `src/margin/dashboard/service.py` | Dashboard services and `DashboardServiceBundle` dependency container. |
| `src/margin/api/routes/dashboard.py` | FastAPI router exposing dashboard BFF endpoints under `/api/v1`. |

### Frontend

| File | Purpose |
|------|---------|
| `web/app/research/page.tsx` | Dashboard home page (server component). |
| `web/app/research/loading.tsx` | Loading UI for the dashboard home. |
| `web/app/research/page.test.tsx` | Unit tests for the dashboard home page. |
| `web/app/research/actions.ts` | Server action to create a research run. |
| `web/app/research/runs/[runId]/page.tsx` | Run detail page (server component). |
| `web/app/research/runs/[runId]/loading.tsx` | Loading UI for the run detail page. |
| `web/app/research/items/[itemId]/page.tsx` | Item detail page (server component). |
| `web/app/research/items/[itemId]/loading.tsx` | Loading UI for the item detail page. |
| `web/app/research/items/[itemId]/actions.ts` | Server action to record item feedback. |
| `web/components/candidate-card.tsx` | Card rendering a single research candidate. |
| `web/components/candidate-card.test.tsx` | Unit tests for `CandidateCard`. |
| `web/components/candidate-list.tsx` | Grid of candidate cards. |
| `web/components/evidence-panel.tsx` | Evidence expansion panel. |
| `web/components/evidence-panel.test.tsx` | Unit tests for `EvidencePanel`. |
| `web/components/report-panel.tsx` | Report preview and export download. |
| `web/components/report-panel.test.tsx` | Unit tests for `ReportPanel`. |
| `web/components/valuation-panel.tsx` | Valuation range and risk score panel. |
| `web/components/home-summary.tsx` | Six-block home summary grid. |
| `web/components/home-summary.test.tsx` | Unit tests for `HomeSummary`. |
| `web/components/research-status-badge.tsx` | Status badge for research items. |
| `web/components/research-run-form.tsx` | Form to trigger a research run. |
| `web/components/research-feedback-form.tsx` | Form to record item feedback. |
| `web/components/provider-status-panel.tsx` | Provider health status list. |
| `web/components/page-loading.tsx` | Skeleton loading screen. |
| `web/components/position-review-badge.tsx` | Position review status badge. |
| `web/lib/api.ts` | API client types and fetch wrappers used by dashboard pages. |

---

## 3. Domain Models

All domain models live in `src/margin/dashboard/models.py` and are immutable Pydantic models (`model_config = {"frozen": True}`). Timestamps are normalized to UTC via `ensure_utc`.

### Enums

| Enum | Values | Description |
|------|--------|-------------|
| `RunStatus` | `published`, `abstained`, `aborted`, `partial` | Terminal state of a dashboard run. |
| `ItemStatus` | `published`, `abstained`, `aborted`, `data_missing` | Status of a single research item. |
| `FeedbackType` | `accept`, `reject`, `watch`, `comment` | Allowed user feedback actions. |
| `JobStatus` | `completed`, `failed` | Synchronous MVP job status. |
| `ReportFormat` | `markdown`, `json` | Supported report export formats. |

### `ResearchRun`

Run-level immutable aggregate for dashboard queries.

| Field | Type | Description |
|-------|------|-------------|
| `run_id` | `str` | Auto-generated `dr_<hex>` identifier. |
| `decision_at` | `datetime` | Decision timestamp for the run. |
| `strategy_id` | `str` | Strategy identifier. |
| `version_id` | `str` | Strategy version identifier. |
| `portfolio_id` | `str \| None` | Optional linked portfolio. |
| `universe` | `list[str]` | Symbols processed in the run. |
| `status` | `RunStatus` | Aggregated terminal status. |
| `summary` | `str` | Human-readable run summary. |
| `item_count` | `int` | Total items. |
| `published_count` | `int` | Published items. |
| `abstained_count` | `int` | Abstained items. |
| `aborted_count` | `int` | Aborted items. |
| `created_at` | `datetime` | Run creation timestamp. |

### `ResearchItem`

Symbol-level item generated from a module 06 workflow result.

| Field | Type | Description |
|-------|------|-------------|
| `item_id` | `str` | Auto-generated `di_<hex>` identifier. |
| `run_id` | `str` | Parent run identifier. |
| `symbol` | `str` | Ticker/symbol. |
| `signal_type` | `str` | Signal classification string. |
| `confidence` | `float` | Confidence in `[0, 1]`. |
| `statement` | `str` | Research conclusion statement. |
| `workflow_run_id` | `str` | Linked module 06 workflow run. |
| `snapshot_id` | `str \| None` | Linked module 06 snapshot. |
| `status` | `ItemStatus` | Dashboard item status. |
| `abstain_reason` | `str \| None` | Reason for abstain, if any. |
| `rejection_reasons` | `list[str]` | List of rejection reasons. |
| `evidence_ids` | `list[str]` | Evidence reference identifiers. |
| `claim_ids` | `list[str]` | Claim reference identifiers. |
| `risk_score` | `float \| None` | Optional risk score. |
| `counter_arguments` | `list[str]` | Counter-argument strings. |
| `portfolio_constraint_violations` | `list[str]` | Portfolio constraint violations. |
| `created_at` | `datetime` | Item creation timestamp. |

### `CandidateCard`

Derived candidate card used by the research dashboard UI.

| Field | Type | Description |
|-------|------|-------------|
| `item_id` | `str` | Item identifier. |
| `run_id` | `str` | Parent run identifier. |
| `symbol` | `str` | Ticker/symbol. |
| `signal_type` | `str` | Signal classification. |
| `confidence` | `float` | Confidence score. |
| `statement` | `str` | Conclusion statement. |
| `current_price` | `float \| None` | Optional current price. |
| `quantitative_rank` | `int \| None` | Optional quantitative rank. |
| `research_status` | `str` | Research item status string. |
| `position_review_status` | `str \| None` | Optional position review status. |
| `valuation_range` | `tuple[float, float] \| None` | Base valuation range. |
| `margin_of_safety` | `float \| None` | Margin of safety. |
| `value_trap_score` | `float \| None` | Value-trap risk score. |
| `event_window` | `str \| None` | Optional event window. |
| `catalysts` | `list[str]` | Catalyst list. |
| `counter_arguments` | `list[str]` | Counter-arguments. |
| `evidence_summary` | `dict[str, Any]` | Evidence count and level distribution. |
| `watch_conditions` | `list[str]` | Conditions to keep watching. |
| `invalidation_conditions` | `list[str]` | Invalidation conditions. |
| `strategy_version` | `str` | Strategy version. |
| `disclaimer` | `str` | Default Chinese disclaimer. |

### `HomeSummary`

Six-block home summary for the research candidate dashboard.

| Field | Type | Description |
|-------|------|-------------|
| `decision_at` | `datetime \| None` | Latest run decision timestamp. |
| `run_id` | `str \| None` | Latest run identifier. |
| `strategy_id` | `str \| None` | Latest strategy identifier. |
| `version_id` | `str \| None` | Latest strategy version. |
| `run_status` | `str \| None` | Latest run status. |
| `today_candidates` | `list[CandidateCard]` | Today's research candidates. |
| `position_reviews` | `list[CandidateCard]` | Existing position review reminders. |
| `high_priority_risks` | `list[CandidateCard]` | High-priority risk cards. |
| `rejections` | `list[CandidateCard]` | Rejected cards. |
| `run_stats` | `dict[str, int]` | Run statistics. |

### `EvidenceView`

Expanded evidence view for a research item.

| Field | Type | Description |
|-------|------|-------------|
| `item_id` | `str` | Item identifier. |
| `claims` | `list[ClaimView]` | Rendered claims. |
| `evidence_by_level` | `dict[str, list[EvidenceLocator]]` | Locators grouped by source level. |
| `source_distribution` | `dict[str, int]` | Count per source level. |
| `overall_confidence` | `float` | Aggregated confidence. |
| `locators_available` | `bool` | Whether locators exist. |

### `ValuationView`

Valuation view for a research item.

| Field | Type | Description |
|-------|------|-------------|
| `item_id` | `str` | Item identifier. |
| `base_valuation_range` | `tuple[float, float] \| None` | Base valuation range. |
| `pessimistic_range` | `tuple[float, float] \| None` | Pessimistic valuation range. |
| `margin_of_safety` | `float \| None` | Margin of safety. |
| `value_trap_score` | `float \| None` | Value-trap risk score. |
| `method` | `str \| None` | Valuation method. |
| `notes` | `str` | Human-readable notes. |

### `ResearchReport`

Rendered research report for a dashboard item.

| Field | Type | Description |
|-------|------|-------------|
| `item_id` | `str` | Item identifier. |
| `run_id` | `str` | Parent run identifier. |
| `symbol` | `str` | Ticker/symbol. |
| `title` | `str` | Report title. |
| `format` | `ReportFormat` | Report format. |
| `content` | `str` | Rendered Markdown content. |
| `sections` | `dict[str, Any]` | Structured report sections. |
| `generated_at` | `datetime` | Generation timestamp. |

### Additional Models

| Model | Purpose |
|-------|---------|
| `EvidenceLocator` | Dashboard-friendly evidence locator with `evidence_id`, `source_level`, `source_url`, `content`, `page`, `section`. |
| `ClaimView` | Claim rendered in the evidence panel. |
| `FeedbackRecord` | Append-only user feedback for a research item. |
| `ProviderStatus` | Health metadata for a dashboard-facing provider or subsystem. |
| `JobRun` | Synchronous MVP job record for nightly run endpoints. |
| `AuditView` | Audit trace for a research dashboard item. |
| `ReportExport` | Export payload for a rendered dashboard research report. |

---

## 4. Services

All services live in `src/margin/dashboard/service.py`.

### `DashboardResearchService`

Runs module 06 workflows and aggregates them into module 08 runs/items.

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `__init__` | `research_service: Any`, `repository: DashboardRepository` | - | Stores research service and repository. |
| `run_batch` | `decision_at: datetime \| None`, `strategy_id: str`, `version_id: str`, `portfolio_id: str \| None`, `symbols: list[str] \| None` | `ResearchRun` | Runs one workflow per symbol, derives statuses, persists run and items, returns the run. |
| `_item_from_result` | `run_id: str`, `symbol: str`, `result: WorkflowResult` | `ResearchItem` | Converts a module 06 workflow result into a dashboard item. |

### `DashboardQueryService`

Read-only dashboard query service and card/home-summary BFF.

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `__init__` | `repository: DashboardRepository`, `research_repository: ResearchRepository` | - | Stores both repositories. |
| `list_runs` | `strategy_id`, `portfolio_id`, `status`, `limit=100` | `list[ResearchRun]` | Lists dashboard runs sorted newest first. |
| `get_run` | `run_id: str` | `ResearchRun` | Returns one run or raises `KeyError`. |
| `get_run_items` | `run_id: str` | `list[ResearchItem]` | Returns items for a run. |
| `get_item` | `item_id: str` | `ResearchItem` | Returns one item or raises `KeyError`. |
| `get_candidate_cards` | `run_id: str` | `list[CandidateCard]` | Builds candidate cards for a run. |
| `get_home_summary` | `portfolio_id=None`, `strategy_id=None` | `HomeSummary` | Builds the six-block home summary from the latest run. |
| `_card_from_item` | `run: ResearchRun`, `item: ResearchItem` | `CandidateCard` | Derives a card from an item plus valuation view. |

### `EvidenceViewService`

Builds an evidence expansion view from item and snapshot metadata.

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `__init__` | `repository: DashboardRepository`, `research_repository: ResearchRepository` | - | Stores repositories. |
| `get_evidence_view` | `item_id: str` | `EvidenceView` | Returns claims, locators, source distribution, and confidence. |

### `ValuationViewService`

Builds valuation details from module 06 snapshot prior outputs.

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `__init__` | `repository: DashboardRepository`, `research_repository: ResearchRepository` | - | Stores repositories. |
| `get_valuation_view` | `item_id: str` | `ValuationView` | Extracts valuation range from `valuation_tool` output; falls back to unavailable notes. |

### `FeedbackService`

Appends feedback without mutating immutable research items.

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `__init__` | `repository: DashboardRepository` | - | Stores repository. |
| `record_feedback` | `item_id: str`, `feedback_type: FeedbackType`, `comment: str = ""` | `FeedbackRecord` | Validates item exists, persists feedback record. |

### `AuditService`

Returns module 06 snapshot audit metadata for a dashboard item.

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `__init__` | `repository: DashboardRepository`, `research_repository: ResearchRepository` | - | Stores repositories. |
| `get_audit_view` | `item_id: str` | `AuditView` | Returns snapshot trace/input/output hashes and tool-call identifiers. |

### `ReportRenderer`

Renders a dashboard item into an auditable research report.

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `__init__` | `repository: DashboardRepository`, `research_repository: ResearchRepository` | - | Stores repositories. |
| `render_report` | `item_id: str` | `ResearchReport` | Builds summary, valuation, evidence, audit sections and Markdown content. |

### `ExportService`

Exports rendered dashboard reports in lightweight MVP formats.

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `__init__` | `renderer: ReportRenderer` | - | Stores renderer. |
| `export_report` | `item_id: str`, `report_format: str \| ReportFormat = ReportFormat.MARKDOWN` | `ReportExport` | Renders report and serializes as Markdown or JSON. |

### `ProviderStatusService`

Provider health service for the dashboard BFF.

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `__init__` | `providers: list[Any] \| None = None` | - | Stores provider list. |
| `list_status` | - | `list[ProviderStatus]` | Calls `healthcheck()` on each provider; returns a default healthy dashboard status when no providers are configured. |

### `JobService`

Synchronous job registry for v0.1 nightly run endpoints.

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `__init__` | - | - | Initializes in-memory job map. |
| `record_completed_job` | `run_id: str` | `JobRun` | Records a completed job linked to a run. |
| `get_job` | `job_run_id: str` | `JobRun` | Returns a job or raises `KeyError`. |

### `DashboardServiceBundle`

Container for FastAPI dependency injection.

| Field | Type | Description |
|-------|------|-------------|
| `research` | `DashboardResearchService` | Batch run orchestration. |
| `query` | `DashboardQueryService` | Read queries. |
| `evidence` | `EvidenceViewService` | Evidence expansion. |
| `valuation` | `ValuationViewService` | Valuation view. |
| `feedback` | `FeedbackService` | Feedback recording. |
| `audit` | `AuditService` | Audit metadata. |
| `reports` | `ReportRenderer` | Report rendering. |
| `exports` | `ExportService` | Report export. |
| `providers` | `ProviderStatusService` | Provider status. |
| `jobs` | `JobService` | Job registry. |

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `in_memory` | `dashboard_repository`, `research_repository`, `research_service` | `DashboardServiceBundle` | Factory using in-memory repositories for tests. |
| `from_repositories` | `dashboard_repository`, `research_repository`, `research_service`, `providers` | `DashboardServiceBundle` | Production factory wiring all services. |

### Module-Private Helpers

| Function | Description |
|----------|-------------|
| `_item_status(state, signal_type)` | Maps `WorkflowState` and `SignalType` to `ItemStatus`. |
| `_run_status(published, abstained, aborted, total)` | Derives `RunStatus` from item counts. |
| `_must_get_item(repository, item_id)` | Fetches an item or raises `KeyError`. |
| `_snapshot_prior_outputs(snapshot)` | Parses `agent_outputs_json` from a module 06 snapshot. |
| `_coerce_report_format(value)` | Validates and returns a `ReportFormat`. |
| `_render_markdown_report(title, sections)` | Renders Chinese Markdown report content. |

---

## 5. Repository

Repository code lives in `src/margin/dashboard/repository.py`.

### `DashboardRepository` (Protocol)

| Method | Parameters | Returns | Description |
|--------|------------|---------|-------------|
| `add_run` | `run: ResearchRun` | `None` | Persist a dashboard run. |
| `get_run` | `run_id: str` | `ResearchRun \| None` | Return one run by identifier. |
| `list_runs` | `strategy_id`, `portfolio_id`, `status`, `limit=100` | `list[ResearchRun]` | Return dashboard runs sorted newest first. |
| `add_items` | `items: list[ResearchItem]` | `None` | Persist run items. |
| `get_item` | `item_id: str` | `ResearchItem \| None` | Return one item by identifier. |
| `list_items` | `run_id: str` | `list[ResearchItem]` | Return all items for a run. |
| `add_feedback` | `feedback: FeedbackRecord` | `None` | Append user feedback. |
| `list_feedback` | `item_id: str` | `list[FeedbackRecord]` | Return feedback for one item. |

### `MemoryDashboardRepository`

In-memory dashboard repository for tests and local usage.

| Method | Description |
|--------|-------------|
| `__init__` | Initializes internal `_runs`, `_items`, `_feedback` dictionaries. |
| `add_run` | Stores run in `_runs`. |
| `get_run` | Looks up run in `_runs`. |
| `list_runs` | Filters and sorts `_runs` values by `created_at` descending. |
| `add_items` | Stores items in `_items`. |
| `get_item` | Looks up item in `_items`. |
| `list_items` | Filters items by `run_id` and sorts by `created_at`. |
| `add_feedback` | Appends feedback to `_feedback[item_id]`. |
| `list_feedback` | Returns a copy of feedback list for an item. |

### `SQLAlchemyDashboardRepository`

PostgreSQL-backed dashboard repository.

| Method | Description |
|--------|-------------|
| `__init__(session_factory)` | Stores a callable that returns SQLAlchemy sessions. |
| `add_run` | Merges a `DashboardRunRow` in a transaction. |
| `get_run` | Fetches `DashboardRunRow` by primary key. |
| `list_runs` | Builds a filtered `select(DashboardRunRow)` ordered by `created_at.desc()`. |
| `add_items` | Merges each `DashboardItemRow` in a transaction. |
| `get_item` | Fetches `DashboardItemRow` by primary key. |
| `list_items` | Selects items by `run_id` ordered by `created_at`. |
| `add_feedback` | Inserts a `DashboardFeedbackRow`. |
| `list_feedback` | Selects feedback by `item_id` ordered by `created_at`. |

### Row Mapping Functions

| Function | Description |
|----------|-------------|
| `_run_to_row(run)` | Converts `ResearchRun` to `DashboardRunRow`. |
| `_item_to_row(item)` | Converts `ResearchItem` to `DashboardItemRow`. |
| `_run_from_row(row)` | Converts `DashboardRunRow` to `ResearchRun`. |
| `_item_from_row(row)` | Converts `DashboardItemRow` to `ResearchItem`. |

---

## 6. FastAPI Endpoints

All endpoints are defined in `src/margin/api/routes/dashboard.py` and mounted under `/api/v1` with the tag `dashboard`.

### Request/Response Models

| Model | Fields | Purpose |
|-------|--------|---------|
| `ResearchRunCreate` | `strategy_id`, `version_id="default"`, `decision_at`, `portfolio_id`, `symbols` | Trigger a dashboard research run. |
| `FeedbackCreate` | `feedback_type`, `comment` | Record item feedback. |

### Endpoints

| Method | Path | Summary | Request | Response |
|--------|------|---------|---------|----------|
| `GET` | `/research-runs` | List dashboard research runs | Query: `strategy_id`, `portfolio_id`, `status`, `limit` | `list[ResearchRun]` |
| `POST` | `/research-runs` | Trigger a synchronous MVP research run | Body: `ResearchRunCreate` | `ResearchRun` (201) |
| `GET` | `/research-runs/{run_id}` | Return one dashboard run | Path: `run_id` | `ResearchRun` |
| `GET` | `/research-runs/{run_id}/items` | Return items for a dashboard run | Path: `run_id` | `list[ResearchItem]` |
| `GET` | `/research-runs/{run_id}/cards` | Return candidate cards for a dashboard run | Path: `run_id` | `list[CandidateCard]` |
| `GET` | `/research-home` | Return the dashboard home summary | Query: `strategy_id`, `portfolio_id` | `HomeSummary` |
| `GET` | `/research-items/{item_id}` | Return one research item | Path: `item_id` | `ResearchItem` |
| `GET` | `/research-items/{item_id}/evidence` | Return expanded evidence for a research item | Path: `item_id` | `EvidenceView` |
| `GET` | `/research-items/{item_id}/valuation` | Return valuation details for a research item | Path: `item_id` | `ValuationView` |
| `GET` | `/research-items/{item_id}/audit` | Return audit metadata for a research item | Path: `item_id` | `AuditView` |
| `GET` | `/research-items/{item_id}/report` | Return a rendered research report | Path: `item_id` | `ResearchReport` |
| `GET` | `/research-items/{item_id}/export` | Return a JSON-wrapped export payload | Path: `item_id`, Query: `format` | `ReportExport` |
| `POST` | `/research-items/{item_id}/feedback` | Append feedback for a research item | Path: `item_id`, Body: `FeedbackCreate` | `FeedbackRecord` (201) |
| `GET` | `/provider-status` | Return provider health status | - | `list[ProviderStatus]` |
| `POST` | `/jobs/nightly-runs` | Trigger a synchronous nightly run and return its job record | Body: `ResearchRunCreate` | `JobRun` (201) |
| `GET` | `/jobs/{job_run_id}` | Return a dashboard job record | Path: `job_run_id` | `JobRun` |

All endpoints catch `KeyError` and convert it to `HTTPException(status_code=404)`.

---

## 7. Next.js Pages and Server Actions

### `ResearchDashboardPage`

**File:** `web/app/research/page.tsx`

Default async server component. Marked `dynamic = "force-dynamic"`.

| Aspect | Description |
|--------|-------------|
| Data fetching | Parallel fetch of `fetchResearchHome`, `fetchResearchRuns`, `fetchProviderStatus`; then `fetchResearchRunCards` for the most recent run. |
| Error handling | Catches exceptions and renders a Chinese error notice. |
| Render | Workspace header, run form, provider status panel, home summary, and today's candidate list. |

### `createResearchRunAction`

**File:** `web/app/research/actions.ts`

Server action that creates a research run.

| Aspect | Description |
|--------|-------------|
| Inputs | `FormData` with `strategy_id`, `version_id`, `portfolio_id`, `symbols`. |
| Validation | `requiredText`, `optionalText`, and `splitSymbols` helpers parse and trim values. |
| API call | `createResearchRun({ strategy_id, version_id, portfolio_id, symbols })`. |
| Side effects | `revalidatePath("/research")` and `redirect(`/research/runs/${run.run_id}`)`. |

### `ResearchRunPage`

**File:** `web/app/research/runs/[runId]/page.tsx`

Run detail server component.

| Aspect | Description |
|--------|-------------|
| Params | `Promise<{ runId: string }>`. |
| Data fetching | Parallel fetch of `fetchResearchRun(runId)` and `fetchResearchRunCards(runId)`. |
| Render | Workspace header with run status and item count, plus `CandidateList`. |

### `ResearchItemPage`

**File:** `web/app/research/items/[itemId]/page.tsx`

Item detail server component.

| Aspect | Description |
|--------|-------------|
| Params | `Promise<{ itemId: string }>`. |
| Data fetching | Parallel fetch of item, evidence, valuation, audit, report, and JSON export. |
| Render | Header with symbol and status badge, thesis block, valuation panel, evidence panel, report panel, and feedback form. |

### `createResearchFeedbackAction`

**File:** `web/app/research/items/[itemId]/actions.ts`

Server action that records feedback for a research item.

| Aspect | Description |
|--------|-------------|
| Inputs | Bound `itemId` and `FormData` with `feedback_type`, `comment`. |
| Validation | `feedbackType` helper restricts values to `accept`, `reject`, `watch`, `comment`. |
| API call | `createResearchItemFeedback(itemId, { feedback_type, comment })`. |
| Side effects | `revalidatePath(`/research/items/${itemId}`)`. |

### Loading Components

| File | Purpose |
|------|---------|
| `web/app/research/loading.tsx` | Renders `PageLoading` with eyebrow "Research" and title "研究候选面板". |
| `web/app/research/runs/[runId]/loading.tsx` | Renders `PageLoading` with eyebrow "Research Run" and title "研究运行". |
| `web/app/research/items/[itemId]/loading.tsx` | Renders `PageLoading` with eyebrow "Research Item" and title "研究详情". |

---

## 8. React Components

### `CandidateCard`

**File:** `web/components/candidate-card.tsx`

Renders a single research candidate card.

| Prop | Type | Description |
|------|------|-------------|
| `card` | `ResearchCandidateCard` | Candidate data. |

**Behavior:**
- Displays symbol as a link to `/research/items/{item_id}`.
- Shows `ResearchStatusBadge` and `PositionReviewBadge`.
- Renders confidence, valuation range, value-trap score, and evidence count.
- Lists counter-arguments when present.
- Shows strategy version and disclaimer footer.

### `CandidateList`

**File:** `web/components/candidate-list.tsx`

Grid container for candidate cards.

| Prop | Type | Description |
|------|------|-------------|
| `cards` | `ResearchCandidateCard[]` | Cards to render. |

**Behavior:** Renders an empty-state message when `cards` is empty; otherwise maps cards to `CandidateCard` in a grid.

### `EvidencePanel`

**File:** `web/components/evidence-panel.tsx`

Evidence expansion panel.

| Prop | Type | Description |
|------|------|-------------|
| `evidence` | `EvidenceView \| null` | Evidence data. |

**Behavior:**
- Shows empty state when evidence is missing or `locators_available` is false.
- Flattens `evidence_by_level` into locators with level labels.
- Renders claims with statement, fact/inference, and confidence.
- Renders source locators with section, page, and external link.

### `ReportPanel`

**File:** `web/components/report-panel.tsx`

Report preview and export download.

| Prop | Type | Description |
|------|------|-------------|
| `report` | `ResearchReport \| null` | Rendered report. |
| `exported` | `ReportExport \| null` | Export payload. |

**Behavior:**
- Shows empty state when report is missing.
- Displays report title, export filename, MIME type.
- Renders a data-URI download link when `exported` is present.
- Shows first 8 lines of Markdown content in a `<pre>` block.

### `ValuationPanel`

**File:** `web/components/valuation-panel.tsx`

Valuation range and risk score panel.

| Prop | Type | Description |
|------|------|-------------|
| `valuation` | `ValuationView \| null` | Valuation data. |

**Behavior:**
- Shows empty state when valuation is missing.
- Formats base and pessimistic ranges as CNY currency.
- Formats value-trap score as percentage.
- Displays valuation method and notes.

### `HomeSummary`

**File:** `web/components/home-summary.tsx`

Six-block home summary grid.

| Prop | Type | Description |
|------|------|-------------|
| `summary` | `ResearchHomeSummary \| null` | Home summary data. |

**Behavior:** Renders six metric tiles: market status summary, today's candidates, position reviews, high-priority risks, rejections, and strategy run status. Uses internal `SummaryTile` helper.

### `ResearchStatusBadge`

**File:** `web/components/research-status-badge.tsx`

Status badge for research items.

| Prop | Type | Description |
|------|------|-------------|
| `status` | `string` | Status value. |

**Behavior:** Maps status to Chinese label and applies `positive`, `watch`, or `data_missing` tone class.

### `ResearchRunForm`

**File:** `web/components/research-run-form.tsx`

Form to trigger a research run.

| Prop | Type | Description |
|------|------|-------------|
| `action` | `(formData: FormData) => void \| Promise<void>` | Server action handler. |

**Behavior:** Renders fields for `strategy_id`, `version_id`, `portfolio_id`, and `symbols`, then submits to the provided action.

### `ResearchFeedbackForm`

**File:** `web/components/research-feedback-form.tsx`

Form to record item feedback.

| Prop | Type | Description |
|------|------|-------------|
| `action` | `(formData: FormData) => void \| Promise<void>` | Server action handler. |

**Behavior:** Renders a select for `feedback_type` and textarea for `comment`, then submits to the provided action.

### `ProviderStatusPanel`

**File:** `web/components/provider-status-panel.tsx`

Provider health status list.

| Prop | Type | Description |
|------|------|-------------|
| `providers` | `ProviderStatus[]` | Provider statuses. |
| `title` | `string` | Optional panel title. |

**Behavior:** Renders each provider with name, message, and status badge. Shows empty state when no providers.

### `PageLoading`

**File:** `web/components/page-loading.tsx`

Skeleton loading screen.

| Prop | Type | Description |
|------|------|-------------|
| `title` | `string` | Page title. |
| `eyebrow` | `string` | Eyebrow label. |

**Behavior:** Renders header, four skeleton metric tiles, and two skeleton panels.

### `PositionReviewBadge`

**File:** `web/components/position-review-badge.tsx`

Position review status badge.

| Prop | Type | Description |
|------|------|-------------|
| `status` | `string \| null` | Position review status. |

**Behavior:** Maps status to Chinese label with `positive`, `watch`, or `data_missing` tone; renders "未绑定组合" when null.

---

## 9. Cross-Module Usage Notes

### Dependency on Module 06 (Research)

- `DashboardResearchService.run_batch` invokes `research_service.run(...)` for each symbol and converts the returned `WorkflowResult` into `ResearchItem`.
- `EvidenceViewService`, `ValuationViewService`, `AuditService`, and `ReportRenderer` all read `ResearchSnapshot` via `ResearchRepository.get_snapshot(item.snapshot_id)`.
- `ValuationViewService` parses the `valuation_tool` and `risk_review` entries from `snapshot.agent_outputs_json`.
- `AuditService` exposes `workflow_state`, `input_hash`, `output_hash`, `traces`, and `tool_call_ids` from the module 06 snapshot.

### Dependency on Portfolio/Strategy Modules

- `ResearchRun.portfolio_id` and `DashboardQueryService.get_home_summary` accept optional `portfolio_id` and `strategy_id` filters.
- `CandidateCard.position_review_status` is designed to integrate with holdings monitoring (module 09) statuses such as `THESIS_VALID`, `REVIEW_REQUIRED`, `RISK_ALERT`, `THESIS_INVALIDATED`.
- `item.portfolio_constraint_violations` is populated from module 06 signals and surfaced in candidate cards and reports.

### Provider Status Integration

- `ProviderStatusService` consumes a list of provider objects implementing `healthcheck()`.
- `margin.api.dependencies.build_provider_status_providers` supplies LLM, embedding, web search, and rerank providers (or degraded placeholders when unconfigured).
- Missing providers are reported as `unhealthy` with configuration guidance, so the frontend shows explicit gaps.

### Persistence and Migrations

- PostgreSQL schema is created by `alembic/versions/20260619_0007_dashboard.py`.
- Tables: `dashboard_runs`, `dashboard_items`, `dashboard_feedback`.
- `SQLAlchemyDashboardRepository` maps domain models to `DashboardRunRow`, `DashboardItemRow`, and `DashboardFeedbackRow`.

### API Wiring

- `margin.api.main.create_app` includes `dashboard_router` under `/api/v1`.
- `margin.api.dependencies.get_dashboard_services` builds a production `DashboardServiceBundle` with PostgreSQL repositories and the configured research service.
- Tests in `tests/api/test_dashboard.py` use `DashboardServiceBundle.in_memory` and `create_app(dashboard_services=bundle)` for dependency override.

### Frontend API Client

- `web/lib/api.ts` defines TypeScript types mirroring backend Pydantic models and exports fetch functions such as `fetchResearchRuns`, `fetchResearchRunCards`, `fetchResearchHome`, `fetchResearchItemEvidence`, `fetchResearchItemValuation`, `fetchResearchItemReport`, `fetchResearchItemExport`, `fetchProviderStatus`, `createResearchRun`, and `createResearchItemFeedback`.
- GET requests use Next.js `revalidate: 30` caching; mutations use `cache: "no-store"`.
