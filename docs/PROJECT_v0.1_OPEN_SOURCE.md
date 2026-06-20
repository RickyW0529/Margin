# Margin v0.1 Open Source Project Guide

Margin is a local-first, evidence-driven investment research system. v0.1 connects portfolio data, source snapshots, vector retrieval, AI research, candidate dashboards, holdings monitoring, audit records, and Docker Compose deployment.

This document is written for open-source users and contributors. It describes what the current repository actually does, what you need to run it, and where to contribute safely.

> Margin is not financial advice. It does not place trades, does not store brokerage passwords, and does not promise returns.

## 1. What v0.1 Delivers

| Area | Current capability |
| --- | --- |
| Local deployment | Docker Compose stack with postgres, migrate, seed, api, worker, web, prometheus, grafana |
| Portfolio | demo portfolio, manual trades, CSV import, position calculation, portfolio dashboard |
| Research | synchronous MVP research run, internal tools, LLM provider, candidate cards, audit snapshots |
| Evidence | document events, snapshots, chunking, embeddings, pgvector, evidence and claim views |
| Strategy | templates, custom strategy config, version lifecycle, prompt generation |
| Dashboard | research runs, cards, evidence, valuation, audit, report, export, feedback |
| Monitoring | holdings alerts, reviews, operation history, behavior metrics |
| Observability | health endpoints, Prometheus metrics, Grafana dashboard, structured logs |
| Safety | no automatic trading, conservative abstain/degradation behavior |

## 2. Architecture at a Glance

```mermaid
flowchart TB
    Web[Next.js Web] --> API[FastAPI API]
    API --> Portfolio[Portfolio]
    API --> Dashboard[Research Dashboard]
    API --> Strategy[Strategy]
    API --> Monitoring[Holdings Monitoring]
    Dashboard --> Research[Research Workflow]
    Research --> Tools[Internal ToolRegistry]
    Tools --> Retrieval[Vector Retrieval]
    Tools --> Market[Market Data]
    Research --> LLM[LLM Provider]
    Retrieval --> Embedding[Embedding Provider]
    Monitoring --> Worker[APScheduler Worker]
    Worker --> PG[(PostgreSQL + pgvector)]
    API --> PG
    API --> Metrics[/metrics]
    Metrics --> Prometheus[Prometheus]
    Prometheus --> Grafana[Grafana]
```

## 3. Requirements

- Docker and Docker Compose;
- Python 3.11+ for local backend development;
- Node 20+ for frontend development;
- optional provider keys:
  - `MARGIN_LLM_API_KEY` for OpenAI-compatible chat completions;
  - `MARGIN_EMBEDDING_API_KEY` for OpenAI-compatible embeddings;
  - `MARGIN_WEBSEARCH_API_KEY` for Tavily WebSearch;
  - `MARGIN_SECRET_TUSHARE_TOKEN` for Tushare;
  - `MARGIN_RERANK_API_KEY` for optional rerank.

The demo stack can start without all optional provider keys. Missing providers degrade conservatively.

## 4. Quick Start with Docker Compose

```bash
cp .env.example .env
# edit .env and add only the provider keys you want to use

docker compose up -d --build
```

Open:

- Web: http://localhost:3000
- API: http://localhost:8000
- Prometheus: http://localhost:9090
- Grafana: http://localhost:3002

Useful checks:

```bash
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8000/health/ready
curl -fsS http://localhost:8000/api/v1/provider-status
curl -fsS http://localhost:8000/api/v1/portfolios/demo
```

`/api/v1/provider-status` reports `openai_llm`, `openai_embedding`, `tavily_websearch`, and `http_rerank`. Configured LLM and embedding providers perform real remote health checks. Missing Tavily or rerank credentials are reported as `degraded` instead of being hidden.

## 5. Local Development

Backend:

```bash
pip install -e ".[dev,data]"
ruff check src tests
pytest -q
```

Frontend:

```bash
cd web
npm ci
npm run lint
npm test
npm run build
```

Compose validation:

```bash
docker compose config --quiet
```

## 6. Configuration

All application settings use the `MARGIN_` prefix and are centralized in `src/margin/settings.py`.

Common variables:

```env
MARGIN_DATABASE_URL=postgresql+psycopg://margin:margin@localhost:5432/margin
MARGIN_LLM_BASE_URL=https://api.deepseek.com
MARGIN_LLM_API_KEY=
MARGIN_LLM_MODEL=deepseek-v4-pro
MARGIN_EMBEDDING_BASE_URL=https://open.bigmodel.cn/api/paas/v4
MARGIN_EMBEDDING_API_KEY=
MARGIN_EMBEDDING_MODEL=embedding-3
MARGIN_EMBEDDING_DIMENSION=2048
MARGIN_WEBSEARCH_API_KEY=
MARGIN_SECRET_TUSHARE_TOKEN=
```

Do not commit `.env`. The repository intentionally keeps `.env.example` empty of real secrets.

## 7. Database Overview

v0.1 uses PostgreSQL with pgvector and Alembic migrations. The current schema contains 29 public tables. Core groups:

- portfolio: `portfolios`, `trades`, `position_theses`;
- news/source: `source_cursors`, `raw_snapshots`, `document_events`, `document_outbox`, `search_queries`, `search_results`, `dedup_records`, `repost_edges`;
- vector: `chunks`, `chunk_embeddings`, `index_audit_records`, `retrieval_audit_records`;
- evidence: `evidence_records`, `evidence_claims`, `evidence_validation_audits`, `research_evidence`;
- research/dashboard: `research_snapshots`, `dashboard_runs`, `dashboard_items`, `dashboard_feedback`;
- strategy: `strategy_profiles`, `strategy_versions`;
- monitoring: `alert_events`, `position_reviews`;
- audit: `audit_records`.

Current positions are calculated from trades and are not stored in a dedicated `positions` table.

## 8. Safety Boundaries

Margin v0.1 intentionally does not include:

- broker order execution;
- brokerage credential storage;
- guaranteed-return language;
- MCP Server or MCP Gateway;
- arbitrary custom HTTP tools;
- multi-tenant SaaS account management;
- redistribution of paid or copyrighted research reports.

AI tools are internal, typed, permissioned, and audited through `ToolRegistry`.

## 9. Current AI Boundaries

The normal research path uses the configured OpenAI-compatible LLM for web-search query generation, text summary, risk review, reflection/counter-argument, and signal composition. Conservative rule paths still take over when market data is degraded, portfolio constraints fail, citation validation fails, or an LLM call fails.

v0.1 records model versions, traces, and structured outputs for `risk_review` and `reflect_counter_argument`, but it does not require every risk or counter-argument to carry its own evidence reference. That stricter evidence grounding is planned for v0.2.

## 10. Recommended Contribution Areas

Good first contribution areas:

- provider adapters with tests and clear licensing notes;
- source parser improvements;
- strategy templates;
- dashboard UX improvements;
- monitoring rules;
- documentation and examples;
- provider observability and degradation tests.
- v0.2 evidence-grounded risk/counter-argument prompts with per-item `evidence_ids` and locators.

Before contributing:

1. read `AGENTS.md`;
2. identify the related `docs/spec/v0.1` module;
3. identify the related `docs/plan/v0.1` task;
4. add tests for new behavior;
5. run backend and frontend verification where relevant.

## 11. Documentation Map

- Design index: `docs/design/v0.1/README.md`
- Product design CN: `docs/design/v0.1/product/Margin_产品设计_v0.1_中文.md`
- Product design EN: `docs/design/v0.1/product/Margin_Product_Design_v0.1_EN.md`
- Architecture design CN: `docs/design/v0.1/architecture/Margin_架构设计_v0.1_中文.md`
- Architecture design EN: `docs/design/v0.1/architecture/Margin_Architecture_Design_v0.1_EN.md`
- Specs: `docs/spec/v0.1/`
- Plans: `docs/plan/v0.1/`

## 12. License

MIT. See `LICENSE`.
