# 08-research_candidate_dashboard Module

This document describes the current research candidate dashboard implementation. v0.2 removed holdings/trading pages and the v0.1 synchronous research-run, candidate-card, home-summary, evidence/valuation/report/export endpoint set. The dashboard is now a mostly read-only user entrypoint that hides provider, scope, BFF, and run details behind backend defaults and settings pages while exposing Q&A, today's recommendations, evidence reasons, and confidence.

## 1. Responsibilities

`08-research_candidate_dashboard` turns persisted candidate and review data into frontend-ready pages.

Current responsibilities:

- server-side paginated visible recommendation queries;
- dedicated `/dashboard/items/[itemId]` company details separating current review, effective assessment, quant visuals, and RAG evidence;
- quant score, risk flag, evidence locator, and version display;
- home recommendation Q&A that answers from candidate data and rejects refresh, sync, settings, or trading intent;
- a recommendation dashboard for stocks, reasons, confidence, quant score, valuation discount, and risk hints;
- one-click "刷新今日研究" on the recommendation dashboard, using default `scope-current` and current time to start valuation discovery, best-effort wake a worker after API acceptance, and show the latest refresh as a live React Flow node graph; while the latest run is non-terminal, starting another refresh is disabled to avoid duplicate queueing;
- dashboard projection is published as soon as the latest quant run finishes, before expensive AI review; when runs share the same decision time, selection is stable by `created_at`, `item_count`, and `run_id` so a newer full-market projection is not hidden by an older one-stock run;
- Provider key configuration with write-only secret handling.
- personal-research information architecture: user-facing pages are limited to Q&A, recommendations, settings, and settings subpages; backend defaults and settings absorb Provider, scope, run, and candidate concepts.

Removed responsibilities:

- old synchronous `POST /api/v1/research-runs`;
- old `CandidateCard` and `HomeSummary` views;
- separate evidence, valuation, audit, report, and export endpoints;
- holdings, position, brokerage, or trade management.

## 2. File Map

| Path | Current role |
| --- | --- |
| `src/margin/dashboard/models.py` | Dashboard DTOs: compatibility run/item aggregates, candidate list/detail DTOs, feedback, provider status, settings views, read-only Copilot response, and job run. |
| `src/margin/dashboard/db_models.py` | SQLAlchemy rows for `dashboard_runs`, `dashboard_items`, and `dashboard_feedback`. |
| `src/margin/dashboard/repository.py` | Memory/PostgreSQL repository with candidate pagination, filtering, sorting, facets, and feedback storage. |
| `src/margin/dashboard/service.py` | `DashboardQueryService`, `FeedbackService`, `ProviderStatusService`, `JobService`, and `DashboardServiceBundle`. |
| `src/margin/dashboard/detail_context.py` | Detail-page context loader. It uses centralized SQL query factories to read research contexts, AI delta reviews, effective assessments, and news documents, and reads PIT-safe trends from the warehouse. |
| `src/margin/api/routes/dashboard.py` | `/api/v1/research`, `/api/v1/research/items/{item_id}`, `/api/v1/research/copilot`, feedback, provider status, and job endpoints. |
| `src/margin/api/routes/valuation_discovery.py` | Refresh entrypoints: `POST /api/v1/valuation-discovery/refreshes` and `GET /api/v1/valuation-discovery/runs/{run_id}`; the start route wakes a valuation worker once in the background so new work does not sit queued until the next polling tick. |
| `web/app/layout.tsx` | Global application shell; sidebar exposes only Q&A, today's recommendations, and settings, while the top bar shows personal research mode. |
| `web/app/page.tsx` | Question-first home page; reads visible recommendation previews and uses the default question "今日推荐股票是什么？" through read-only Copilot. |
| `web/app/dashboard/page.tsx` | Today's recommendation dashboard with latest visible candidates, key reason labels, confidence, quant score, valuation discount, and one-click refresh. |
| `web/app/dashboard/items/[itemId]/page.tsx` | Dedicated recommendation detail route with current/effective review, quant visuals, risk review, and RAG evidence. |
| `web/app/settings/page.tsx` | Settings hub splitting key, data, scope, and strategy configuration into subpages. |
| `web/app/settings/` | Provider, scope, strategy, and data settings subpages; the scope page uses a company-pool selector for CSI500, ALL_A, and CSI300, while advanced version lists still use `ConfigVersionList`. |
| `web/lib/api.ts` | Frontend API client for v0.2 dashboard, valuation discovery, and provider settings. |
| `web/components/current-vs-effective-panel.tsx` | Current review vs effective assessment panel. |
| `web/components/evidence-locator-list.tsx` | Evidence locator rendering; external text is rendered as text. |
| `web/components/metric-trend-chart.tsx` | Compact fixed-size SVG trend chart for price, valuation, ROE, profit, and other detail metrics. |
| `web/hooks/use-dashboard-refresh-run.ts` | Latest dashboard refresh-run state owner: start, load newest run, poll run detail, toggle open/collapsed state, and block duplicate starts while the latest run is non-terminal. |
| `web/lib/refresh-run-graph.ts` | Normalizes sparse valuation discovery step payloads into fixed React Flow node states: completed, active, queued, pending, waiting, and failed. |
| `web/components/dashboard-refresh-control.tsx` | One-click dashboard refresh controller that hides scope/decision inputs, starts valuation discovery with defaults, shows the latest refresh graph in a modal overlay, and disables the action while a non-terminal run exists. |
| `web/components/dashboard-refresh-node-graph.tsx` | React Flow graph for the 12 valuation discovery phases; active nodes pulse, completed nodes are green, queued/waiting nodes are yellow, pending nodes are gray, and failed/upstream-blocked nodes are red. |
| `web/components/recommendation-chat-panel.tsx` | Home Q&A component with default question, loading/error/disabled states, and business-facing reference labels. |
| `web/components/company-pool-selector.tsx` | User-facing company-pool selector showing real member counts and current state for CSI500, ALL_A, and CSI300; unavailable pools are disabled and custom pools are shown as a future entry. |
| `web/components/provider-settings-panel.tsx` | Write-only Provider secret configuration. |

## 3. Backend Models

### 3.1 Internal compatibility aggregates

`ResearchRun` and `ResearchItem` remain as internal dashboard repository aggregates used to convert persisted candidate/review records into list/detail DTOs. They no longer correspond to a public synchronous research-run creation API.

| Model | Key fields |
| --- | --- |
| `ResearchRun` | `run_id`, `decision_at`, `strategy_id`, `version_id`, `universe`, `status`, counts, `created_at`. |
| `ResearchItem` | `item_id`, `run_id`, `symbol`, `signal_type`, `confidence`, `statement`, `workflow_run_id`, `snapshot_id`, `status`, `abstain_reason`, `rejection_reasons`, `evidence_ids`, `claim_ids`, `risk_score`, `counter_arguments`, `created_at`. |

### 3.2 Public DTOs

| Model | Role |
| --- | --- |
| `DashboardFilters` | Candidate filters: screening status, data status, review-required flag, freshness, and query. |
| `DashboardSort` | Safe sort descriptor: `final_score`, `confidence`, `last_checked_at`, or `symbol`; `asc` or `desc`. |
| `DashboardPageInfo` | Cursor pagination metadata. |
| `ResearchCandidateListItemV2` | One candidate row with security, scope, status, risk, review, score, confidence, and timestamp fields. |
| `ResearchCandidateListResponse` | Candidate page with items, page info, facets, as-of timestamp, and scope version. |
| `ResearchItemDetailV2` | Company detail aggregate: `item`, `current_review`, `effective_assessment`, `factors`, `thesis`, `evidence`, and `versions`. |
| `FeedbackRecord` | Append-only user feedback. |
| `ProviderStatus` | Provider health status. |
| `ReadOnlyCopilotResponse` | Read-only Copilot answer and references. |
| `JobRun` | Lightweight job lookup record. |

## 4. Backend Services

| Service | Method | Role |
| --- | --- | --- |
| `DashboardQueryService` | `list_research_candidates_v2(...)` | Returns server-side paginated candidate lists and overlays display fields such as Chinese security names from quant profiles. |
| `DashboardQueryService` | `get_item_detail_v2(item_id)` | Returns company detail by merging quant profiles, research contexts, AI delta reviews, news documents, effective assessments, valuation state, and key trends. |
| `FeedbackService` | `record_feedback(item_id, feedback_type, comment)` | Appends feedback without mutating research items. |
| `ProviderStatusService` | `list_status()` | Runs provider health checks and reports degraded/unhealthy states. |
| `JobService` | `record_completed_job(run_id)` / `get_job(job_run_id)` | Stores and reads lightweight job records. |
| `DashboardServiceBundle` | `in_memory(...)` / `from_repositories(...)` | FastAPI dependency container. |

## 5. Repository and Pagination

`DashboardRepository.list_research_candidates_v2(...)` reads only the latest dashboard run for one scope, then performs filtering, sorting, cursor pagination, and facets on the server so older refreshes do not leak into today's recommendations. Runs are selected by `decision_at desc, created_at desc, item_count desc, run_id desc`; when manual or automated refreshes reuse the same PIT, the newer fuller projection wins over an older one-stock projection.

Filters:

- `screening_status`
- `data_status`
- `review_required`
- `assessment_freshness`
- `query`

Sort fields:

- `final_score`
- `confidence`
- `last_checked_at`
- `symbol`

Pagination uses a base64 JSON cursor containing the previous sort key and item id. The frontend never loads the full market into the browser.

## 6. FastAPI Endpoints

All endpoints are under `/api/v1`.

| Method | Path | Role |
| --- | --- | --- |
| `GET` | `/research` | Candidate list query with scope, universe, filters, cursor, and sort params. |
| `GET` | `/research/items/{item_id}` | Company detail aggregate. |
| `POST` | `/research/copilot` | Read-only Copilot; mutating intent returns `403 copilot_read_only`. |
| `POST` | `/research-items/{item_id}/feedback` | Append user feedback. |
| `GET` | `/provider-status` | Provider health status. |
| `GET` | `/jobs/{job_run_id}` | Job record lookup. |
| `POST` | `/valuation-discovery/refreshes` | Start valuation discovery refresh; local personal mode skips local-admin/CSRF and still requires an idempotency key; after the response is accepted, the route best-effort wakes one worker while the persistent worker keeps polling as a fallback. |
| `GET` | `/valuation-discovery/runs/{run_id}` | Valuation discovery refresh/run progress. |

Removed public endpoints:

- `/research-runs`
- `/research-runs/{run_id}`
- `/research-runs/{run_id}/items`
- `/research-runs/{run_id}/cards`
- `/research-home`
- `/research-items/{item_id}/evidence`
- `/research-items/{item_id}/valuation`
- `/research-items/{item_id}/audit`
- `/research-items/{item_id}/report`
- `/research-items/{item_id}/export`
- `/jobs/nightly-runs`

## 7. Frontend Pages

| Page | Data source | Role |
| --- | --- | --- |
| `/` | `fetchResearchCandidates`, `askReadOnlyCopilot` | Question-first home page. The first screen is a natural-language input, the default question is "今日推荐股票是什么？", and the page shows up to three recommendation previews. |
| `/dashboard` | `fetchResearchCandidates`, `startValuationDiscoveryRefresh`, `fetchValuationDiscoveryRuns`, `fetchResearchRunDetailV2` | Today's recommendation dashboard with latest visible candidates, reason labels, confidence, quant score, and valuation discount; the top "刷新今日研究" action starts valuation discovery with defaults and opens/updates the latest refresh React Flow graph in a modal overlay; clicking a card navigates to the detail subpage. |
| `/dashboard/items/[itemId]` | `fetchResearchItemDetailV2` | Dedicated recommendation detail page with thesis, quant visuals, current/effective review, risk review, and RAG evidence locators. |
| `/settings` | Static subpage index | Settings hub for key, data, scope, and strategy configuration; the main workflow does not expose low-level configuration. |
| `/settings/providers` | Provider config API | Tushare, Tavily, LLM, Embedding, and Rerank key config. |
| `/settings/scope` | Scope config API | User-visible universe and indicator scope. The company-pool section directly shows CSI500, ALL_A, and CSI300 with current selection state; switching a ready pool rolls a new active Research Scope. |
| `/settings/strategy` | Strategy config API | Strategy template, custom prompt, and versions. |

## 8. Frontend Components

| Component | Role |
| --- | --- |
| `DashboardRefreshControl` | One-click refresh entry on today's recommendation page. It calls the refresh API with `scope-current` and current time, opens the latest refresh graph in a modal overlay on success without pushing page content, shows "刷新进行中" and disables the button while the latest run is non-terminal, and shows business-facing setup errors on failure. |
| `DashboardRefreshNodeGraph` | React Flow run graph: active nodes pulse, completed nodes are green, queued/waiting nodes are yellow, pending nodes are gray, and failed or `upstream_failed` nodes are red. |
| `CompanyPoolSelector` | Scope-settings selector for company pools; only persisted pools with real members can be switched, and the current pool is disabled with a "当前使用" state. |
| `RecommendationChatPanel` | User-facing home Q&A with default question, read-only Copilot call, and loading/disabled/error/success states. |
| `CurrentVsEffectivePanel` | Separates current review from effective assessment. |
| `EvidenceLocatorList` | Renders evidence ids, source levels, locators, snapshot ids, news snippets, and whether the document is linked to the current security. |
| `MetricTrendChart` | Renders detail-page metric trends with a stable empty state when fewer than two points are available. |
| `ProviderSettingsPanel` | Write-only Provider secret form. |
| `ProviderStatusPanel` | Provider health list with healthy/blocker counts in the header. |

## 9. Verification

Backend coverage:

- candidate pagination, filters, and facets;
- item detail current/effective separation;
- detail-context merging for Chinese names, deferred AI status, news evidence, missing valuation state, and trend data;
- read-only Copilot mutation rejection;
- feedback append-only behavior;
- memory and PostgreSQL repository conversion;
- provider-status degradation.

Frontend coverage:

- question-first home page and recommendation preview;
- recommendation dashboard list, detail route, quant visuals, RAG evidence, metrics, and empty state;
- recommendation dashboard one-click refresh defaults, backend worker wake-up, duplicate-start prevention for non-terminal runs, latest-run-only React Flow graph, queued/running states, live polling, collapse/expand, and error handling;
- settings hub subpage entrypoints;
- global navigation only exposes Q&A, recommendations, and settings;
- user-facing refresh blocker messages for Tavily/service-not-configured errors;
- provider settings;
- current/effective, evidence locator, Q&A, refresh graph, and settings components.
- news snippets/security-link status in evidence locators and metric trend chart empty states.

Useful commands:

```bash
pytest -q tests/api/test_dashboard_v02.py tests/dashboard
cd web && npx vitest run
cd web && npm run lint
python scripts/smoke_dashboard_e2e.py --base-url http://localhost:3000
```

## 10. Cross-Module Notes

| Module | Relationship |
| --- | --- |
| `07-strategy_config` | Settings subpages rely on versioned config and Secret Store; the main navigation hides low-level configuration details. |
| `11-valuation_discovery` | `DASHBOARD_REFRESH` publishes the latest quant run's pass/near_threshold/watchlist results as the dashboard projection; `/dashboard` and the home preview consume that projection; `/dashboard` can start refreshes and render the latest run status as a React Flow node graph. Detail pages consume research-context and Analysis Mart lineage to show Chinese names, news documents, valuation empty states, and key trends. |
| `06-multi_agent_research` | `/dashboard/items/[itemId]` detail displays AI delta-review current/effective output. |
| `05-rag_evidence` | `/dashboard/items/[itemId]` detail shows evidence locators for the RAG evidence system. |
| `10-deployment_audit` | Provider status, jobs, traces, and smoke checks rely on deployment audit and observability. |
