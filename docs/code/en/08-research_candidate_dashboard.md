# 08-research_candidate_dashboard Module

This document describes the current research candidate dashboard implementation. v0.2 removed holdings/trading pages and the v0.1 synchronous research-run, candidate-card, home-summary, evidence/valuation/report/export endpoint set. The dashboard is now a mostly read-only BFF for valuation discovery and AI delta-review output.

## 1. Responsibilities

`08-research_candidate_dashboard` turns persisted candidate and review data into frontend-ready pages.

Current responsibilities:

- server-side paginated candidate list queries;
- company detail views separating current review from effective assessment;
- quant score, risk flag, evidence locator, version, and feedback display;
- read-only Copilot that answers from dashboard BFF data and rejects refresh, sync, settings, or trading intent;
- Provider health display;
- frontend form for starting valuation discovery refreshes;
- Provider key configuration with write-only secret handling.
- research-flow information architecture: handle Provider/Scope first, then review candidates and evidence, with no holdings or trading entrypoints.

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
| `src/margin/api/routes/dashboard.py` | `/api/v1/research`, `/api/v1/research/items/{item_id}`, `/api/v1/research/copilot`, feedback, provider status, and job endpoints. |
| `src/margin/api/routes/valuation_discovery.py` | Refresh entrypoints: `POST /api/v1/valuation-discovery/refreshes` and `GET /api/v1/valuation-discovery/runs/{run_id}`. |
| `web/app/layout.tsx` | Global application shell; sidebar exposes only implemented routes: workspace, candidates, universe, refresh runs, strategy templates, and Provider/Scope/Strategy settings. |
| `web/app/page.tsx` | Research workspace home from the v0.2 candidate API, including candidate snapshot, recommended workflow, and Provider blockers. |
| `web/app/research/page.tsx` | Research candidate page with summary cards, filters, table, refresh form, provider status, and read-only Copilot. |
| `web/app/research/runs/[runId]/page.tsx` | Valuation discovery run-progress page. |
| `web/app/research/items/[itemId]/page.tsx` | Company detail page. |
| `web/app/research/universe/page.tsx` | Universe configuration explanation page. |
| `web/app/settings/` | Provider, scope, and strategy settings pages. |
| `web/lib/api.ts` | Frontend API client for v0.2 dashboard, valuation discovery, and provider settings. |
| `web/components/research-run-form.tsx` | Starts valuation discovery refreshes. |
| `web/components/research-filter-bar.tsx` | Candidate-list filters. |
| `web/components/research-results-table.tsx` | Candidate table. |
| `web/components/current-vs-effective-panel.tsx` | Current review vs effective assessment panel. |
| `web/components/evidence-locator-list.tsx` | Evidence locator rendering; external text is rendered as text. |
| `web/components/read-only-copilot-panel.tsx` | Read-only Copilot UI. |
| `web/components/provider-settings-panel.tsx` | Write-only Provider secret configuration. |
| `web/components/research-run-progress.tsx` | Valuation discovery run progress UI. |

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
| `DashboardQueryService` | `list_research_candidates_v2(...)` | Returns server-side paginated candidate lists. |
| `DashboardQueryService` | `get_item_detail_v2(item_id)` | Returns company detail with current/effective separation. |
| `FeedbackService` | `record_feedback(item_id, feedback_type, comment)` | Appends feedback without mutating research items. |
| `ProviderStatusService` | `list_status()` | Runs provider health checks and reports degraded/unhealthy states. |
| `JobService` | `record_completed_job(run_id)` / `get_job(job_run_id)` | Stores and reads lightweight job records. |
| `DashboardServiceBundle` | `in_memory(...)` / `from_repositories(...)` | FastAPI dependency container. |

## 5. Repository and Pagination

`DashboardRepository.list_research_candidates_v2(...)` performs filtering, sorting, cursor pagination, and facets on the server.

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
| `POST` | `/valuation-discovery/refreshes` | Start valuation discovery refresh; requires local admin, CSRF, and idempotency key. |
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
| `/` | `fetchResearchCandidates`, `fetchProviderStatus`, provider configs | Research workspace home with candidate summary, latest candidate snapshot, recommended workflow, and provider status. |
| `/research` | `fetchResearchCandidates`, `startValuationDiscoveryRefresh` | Candidate workspace; users filter candidates first, then trigger valuation discovery refreshes and inspect Provider blockers in the right rail. |
| `/research/runs/[runId]` | `fetchResearchRunDetailV2` → `/api/v1/valuation-discovery/runs/{run_id}` | Run progress page. |
| `/research/items/[itemId]` | `fetchResearchItemDetailV2` | Company detail page with current/effective split, factor snapshot, evidence locator, and feedback form; header links to the company quant page. |
| `/research/companies/[symbol]` | `fetchCompanyQuantProfile`, `fetchCompanyAnalysisProfile` | Company quant and analysis profile page; fetches quant result (five-factor radar, rankings, status, rejection reasons) and fourth-layer Analysis Mart (metric percentiles, finding cards) in parallel; Tabs split into Factor Radar, Analysis Metrics, Key Findings, and Rejection Reasons. |
| `/research/universe` | Static/config data | Universe explanation. |
| `/settings/providers` | Provider config API | Tushare, Tavily, LLM, Embedding, and Rerank key config. |
| `/settings/scope` | Scope config API | User-visible universe and indicator scope. |
| `/settings/strategy` | Strategy config API | Strategy template, custom prompt, and versions. |

## 8. Frontend Components

| Component | Role |
| --- | --- |
| `ResearchRunForm` | Starts valuation discovery refreshes; no longer creates old research runs; surfaces local-admin, provider/scope, and Tavily activation blockers with actionable messages. |
| `ResearchFilterBar` | Server-side candidate filters. |
| `ResearchResultsTable` | Candidate table with score, status, risk, and assessment fields. |
| `ResearchRunProgress` | Valuation discovery run progress. |
| `CurrentVsEffectivePanel` | Separates current review from effective assessment. |
| `EvidenceLocatorList` | Renders evidence ids, source levels, locators, and snapshot ids. |
| `ReadOnlyCopilotPanel` | Submits read-only questions and displays references. |
| `ProviderSettingsPanel` | Write-only Provider secret form. |
| `ProviderStatusPanel` | Provider health list with healthy/blocker counts in the header. |
| `ResearchFeedbackForm` | Append-only feedback form. |
| `ResearchStatusBadge` | Status badge. |

## 9. Verification

Backend coverage:

- candidate pagination, filters, and facets;
- item detail current/effective separation;
- read-only Copilot mutation rejection;
- feedback append-only behavior;
- memory and PostgreSQL repository conversion;
- provider-status degradation.

Frontend coverage:

- home candidate summary;
- global navigation only exposes implemented routes;
- `/research` refresh form and candidate table;
- user-facing refresh blocker messages for Tavily/service-not-configured errors;
- valuation discovery run progress page;
- item detail page;
- provider settings;
- current/effective, evidence locator, read-only Copilot, filters, and table components.

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
| `07-strategy_config` | Provider settings, scope, and strategy pages rely on versioned config and Secret Store. |
| `11-valuation_discovery` | `/research` starts refreshes and run pages read valuation discovery progress. |
| `06-multi_agent_research` | Detail pages display AI delta-review current/effective output. |
| `05-rag_evidence` | Detail pages show evidence locators for the RAG evidence system. |
| `10-deployment_audit` | Provider status, jobs, traces, and smoke checks rely on deployment audit and observability. |
