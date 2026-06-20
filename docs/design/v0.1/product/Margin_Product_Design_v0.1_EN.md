# Margin Open Investment Research System | Product Design v0.1

> Document type: Product Design
> Product version: v0.1
> Document version: v0.1
> Status: active
> Current implementation: all 10 v0.1 modules are wired into a local Docker Compose stack
> Positioning: local-first, evidence-driven, configurable personal investment research software
> Disclaimer: Margin is research assistance software. It is not financial advice and does not place trades.

---

## 1. Product Summary

Margin turns a scattered personal investment workflow into an auditable loop:

1. import or seed portfolios and trades;
2. ingest market data, filings, WebSearch results, LLM output, and embeddings through typed providers;
3. snapshot and index source documents;
4. retrieve evidence through hybrid search;
5. run a multi-agent research workflow through audited internal tools;
6. publish candidate cards only when evidence and validation pass;
7. abstain when market data, evidence, citation, or provider quality is insufficient;
8. monitor existing holdings through deterministic alert rules;
9. keep research snapshots, dashboard items, alerts, reviews, and audit records in PostgreSQL.

```mermaid
flowchart LR
    User[User portfolio/trades] --> Portfolio[Portfolio workspace]
    Data[Market/filing/web data] --> Index[Snapshot + indexing]
    Index --> Retrieval[RAG retrieval]
    Strategy[Strategy + prompt + thresholds] --> Workflow[Research workflow]
    Portfolio --> Workflow
    Retrieval --> Workflow
    Workflow --> Cards[Research candidate dashboard]
    Cards --> Evidence[Evidence / valuation / audit / report]
    Portfolio --> Monitoring[Holdings monitoring]
    Evidence --> Monitoring
    Monitoring --> Reviews[Alerts + reviews + operation history]
```

## 2. Product Principles

| Principle | v0.1 behavior |
| --- | --- |
| Local-first | data, snapshots, audit, and provider keys stay in the local runtime |
| Evidence-first | every important conclusion must expose source, time, evidence, or abstain reason |
| Human decision | no broker integration, no automatic orders, no hidden brokerage credentials |
| Configurable strategy | strategy templates, custom JSON config, prompt generation, version lifecycle |
| Conservative degradation | missing data or failed providers produce `ABSTAINED` / `DATA_MISSING` |
| Auditable | runs, items, alerts, reviews, tool calls, and snapshots are persisted |

## 3. Target Users

Margin v0.1 is built for:

- individual investors who manually execute their own trades;
- builders who want a reproducible research loop around A-share data;
- users who want AI output to cite source material instead of returning unsupported opinions;
- developers who want to extend providers, tools, strategies, and monitoring rules.

It is not built for high-frequency trading, broker automation, guaranteed-return recommendations, multi-tenant SaaS, or regulated advisory workflows.

## 4. v0.1 Scope

Included:

- portfolio, trade, CSV import, cost and position calculation;
- AKShare/Tushare data provider boundaries;
- filing snapshots, document events, outbox, WebSearch adapter, deduplication;
- parser, chunker, OpenAI-compatible embedding provider, pgvector persistence, hybrid retrieval;
- evidence records, claims, locators, validation audits;
- audited internal `ToolRegistry`, LLM provider, research workflow and agents;
- strategy templates, custom strategy config, prompt generation, lifecycle states;
- research dashboard: runs, candidate cards, evidence, valuation, audit, report, export, feedback;
- holdings monitoring: P0-P3 alerts, reviews, operation history, behavior metrics;
- Docker Compose deployment, health checks, metrics, Grafana, append-only audit records.

Explicitly excluded from v0.1:

- MCP Server or MCP Gateway;
- user-defined HTTP tools or arbitrary third-party tool runtime;
- broker order placement;
- multi-tenant permissions;
- cloud account system;
- redistribution of paid research reports or paywalled content.

## 5. User Workflows

### 5.1 Local startup

```mermaid
sequenceDiagram
    participant User
    participant Compose as Docker Compose
    participant DB as PostgreSQL
    participant API as FastAPI
    participant Web as Next.js
    participant Worker as APScheduler Worker

    User->>Compose: docker compose up -d --build
    Compose->>DB: start postgres
    Compose->>API: run migrations
    Compose->>API: seed demo data
    Compose->>API: start API
    Compose->>Worker: start monitoring/indexing worker
    Compose->>Web: start web app
    User->>Web: open localhost:3000
```

### 5.2 Research candidate workflow

```mermaid
flowchart TD
    A[Create research run] --> B[DashboardResearchService]
    B --> C[ResearchService]
    C --> D[ToolRegistry]
    D --> E[Market / portfolio / retrieval / WebSearch tools]
    C --> F[LLM provider]
    C --> G[Citation validation]
    G --> H{Validation passes?}
    H -->|yes| P[Published card]
    H -->|no| Q[Abstained card]
    P --> R[Evidence / valuation / audit / report]
    Q --> R
```

### 5.3 Holdings monitoring workflow

The worker periodically reads current positions, fetches latest prices when available, evaluates deterministic rules, writes alert events, and lets the user record reviews from the position detail page.

## 6. Product Surface

```mermaid
flowchart TB
    Home[/ / Home] --> Portfolio[/portfolios/:portfolioId]
    Portfolio --> Position[/positions/:positionId]
    Home --> Research[/research]
    Research --> Item[/research/items/:itemId]
    Research --> Run[/research/runs/:runId]
    Position --> Alerts[Alerts / reviews / history]
    Item --> Evidence[Evidence]
    Item --> Valuation[Valuation]
    Item --> Audit[Audit]
    Item --> Report[Report / export]
```

Current pages:

- home summary;
- portfolio workspace with clickable position rows;
- position detail with thesis, monitoring alerts, history, and metrics;
- research dashboard with latest run and candidate cards;
- research item detail with evidence, valuation, audit, report, and export;
- research run detail.

## 7. Candidate Card Semantics

| Field | Meaning |
| --- | --- |
| `symbol` | target security |
| `research_status` | `published`, `abstained`, `invalidated`, etc. |
| `statement` | concise conclusion |
| `confidence` | confidence in the research conclusion, not a return probability |
| `valuation_range` | valuation band |
| `value_trap_score` | value-trap risk indicator |
| `counter_arguments` | strongest opposing reasons |
| `evidence_summary` | evidence count and source distribution |
| `disclaimer` | compliance notice |

When data or evidence is insufficient, the product must show the abstain state instead of hiding or inventing a conclusion.

## 8. Alerts and Reviews

v0.1 alerts are local structured records, not email/SMS/IM notifications.

| Priority | Meaning |
| --- | --- |
| P0 | immediate review required |
| P1 | high-priority review |
| P2 | medium-priority observation |
| P3 | low-priority information update |

Alerts are appended to `alert_events`; human decisions are appended to `position_reviews`; both appear in operation history.

## 9. Acceptance Criteria

| ID | Criterion |
| --- | --- |
| P-01 | Docker Compose can start postgres, migrate, seed, api, worker, web, prometheus, and grafana |
| P-02 | demo portfolio is visible with holdings |
| P-03 | portfolio rows link to position detail |
| P-04 | research run can create dashboard cards |
| P-05 | insufficient data produces `abstained` rather than a high-confidence signal |
| P-06 | DeepSeek-compatible LLM and Zhipu-compatible embedding providers can be configured through `.env` |
| P-07 | position detail shows alerts, reviews, and history |
| P-08 | `/metrics`, `/health`, `/health/ready`, and `/health/degraded` are available |
| P-09 | all v0.1 specs and plans are active and traceable |

## 10. Known Limitations

- Tavily WebSearch requires `MARGIN_WEBSEARCH_API_KEY`;
- Tushare requires `MARGIN_SECRET_TUSHARE_TOKEN`;
- Rerank is optional;
- real market data availability depends on upstream accessibility and rate limits;
- strategy configuration has backend APIs but not a full v0.1 frontend editor;
- provider secrets are configured through `.env` or environment variables; a frontend provider settings page is v0.2 scope;
- `risk_review` and `reflect_counter_argument` produce structured LLM outputs in v0.1, but do not require each risk or counter-argument to carry its own evidence reference;
- large-scale Parquet/DuckDB analytics are future work.

`GET /api/v1/provider-status` currently reports `openai_llm`, `openai_embedding`, `tavily_websearch`, and `http_rerank`. Configured LLM and embedding providers perform real remote health checks. Missing Tavily or rerank configuration is shown as `degraded` instead of being hidden.

The research signal composer uses the LLM on the normal path, then falls back to conservative rule output when market data is degraded, portfolio constraints fail, citation validation fails, or the LLM call fails.

v0.2 should add evidence-grounded risk/counter-argument generation, including per-item `evidence_ids`, locators, stricter language/output controls, and provider configuration UI.

## 11. Summary

Margin v0.1 delivers a working local research loop: portfolio, evidence, research workflow, candidate dashboard, holdings monitoring, audit, and deployment are connected. Its default behavior is conservative: when evidence is weak or providers degrade, the product abstains instead of generating false confidence.
