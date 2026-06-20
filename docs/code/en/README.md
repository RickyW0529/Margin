# Margin Current Code Documentation Index (English)

This directory contains function-level documentation for the current Margin implementation. It covers backend Python modules, FastAPI endpoints, Next.js pages, React components, and deployment/observability configuration.

## Directory Structure

```
docs/code/en/
├── README.md                         This file
├── 00-shared.md                      Shared and core cross-cutting components
├── 01-data_provider.md               Data Provider module
├── 02-holdings.md                    Holdings / Portfolio module
├── 03-filing_websearch.md            Filing & WebSearch module
├── 04-text_indexing.md               Text Indexing module
├── 05-rag_evidence.md                RAG Evidence module
├── 06-multi_agent_research.md        Multi-Agent Research module
├── 07-strategy_config.md             Strategy Configuration module
├── 08-research_candidate_dashboard.md Research Candidate Dashboard module
├── 09-holdings_monitoring.md         Holdings Monitoring module
└── 10-deployment_audit.md            Deployment & Audit module
```

## Module Index

| ID | Module (slug) | Chinese name | Documentation | Source paths |
|----|---------------|--------------|---------------|--------------|
| 00 | shared | Shared / core cross-cutting | [00-shared.md](./00-shared.md) | `src/margin/settings.py`, `src/margin/worker.py`, `src/margin/storage/`, `src/margin/api/`, `src/margin/core/provider.py`, `src/margin/core/registry.py`, `src/margin/core/resilience.py`, `src/margin/core/secret.py` |
| 01 | data_provider | Data Provider | [01-data_provider.md](./01-data_provider.md) | `src/margin/data/`, `src/margin/core/provider.py`, `src/margin/core/registry.py` |
| 02 | holdings | Holdings | [02-holdings.md](./02-holdings.md) | `src/margin/portfolio/`, `src/margin/api/routes/portfolios.py`, `web/app/portfolios/`, `web/components/portfolio-workspace.tsx` |
| 03 | filing_websearch | Filing & WebSearch | [03-filing_websearch.md](./03-filing_websearch.md) | `src/margin/news/` |
| 04 | text_indexing | Text Indexing | [04-text_indexing.md](./04-text_indexing.md) | `src/margin/vector/` |
| 05 | rag_evidence | RAG Evidence | [05-rag_evidence.md](./05-rag_evidence.md) | `src/margin/evidence/` |
| 06 | multi_agent_research | Multi-Agent Research | [06-multi_agent_research.md](./06-multi_agent_research.md) | `src/margin/research/`, `src/margin/api/routes/research.py` |
| 07 | strategy_config | Strategy Configuration | [07-strategy_config.md](./07-strategy_config.md) | `src/margin/strategy/`, `src/margin/api/routes/strategy.py` |
| 08 | research_candidate_dashboard | Research Candidate Dashboard | [08-research_candidate_dashboard.md](./08-research_candidate_dashboard.md) | `src/margin/dashboard/`, `src/margin/api/routes/dashboard.py`, `web/app/research/`, `web/components/candidate-*.tsx`, `web/components/evidence-panel.tsx`, `web/components/report-panel.tsx`, `web/components/valuation-panel.tsx`, `web/components/home-summary.tsx` |
| 09 | holdings_monitoring | Holdings Monitoring | [09-holdings_monitoring.md](./09-holdings_monitoring.md) | `src/margin/holdings_monitoring/`, `src/margin/api/routes/monitoring.py`, `web/app/positions/`, `web/components/position-detail.tsx`, `web/components/position-review-badge.tsx` |
| 10 | deployment_audit | Deployment & Audit | [10-deployment_audit.md](./10-deployment_audit.md) | `src/margin/core/` (audit, snapshot, degradation, logging, metrics), `src/margin/api/middleware.py`, `src/margin/api/metrics.py`, `src/margin/api/routes/health.py`, `Dockerfile`, `web/Dockerfile`, `docker-compose.yml`, `.github/workflows/ci.yml`, `scripts/`, `docker/prometheus.yml` |

## Documentation Conventions

- Each module document contains: overview, file-level summary, public class/function reference, FastAPI endpoint tables, frontend component reference, and cross-module dependency notes.
- Class methods and functions are presented in Markdown tables with signatures, parameters, and return values; type annotations are preserved from the source.
- Docstrings are used where present; otherwise descriptions are inferred from the code.
- Only public interfaces and key implementation details are described; internal boilerplate is omitted.

## How to Use

- **Find by module**: open the corresponding numbered markdown file.
- **Trace cross-module dependencies**: see the "Cross-Module Usage Notes" section at the end of each document.
- **Map to design**: code docs describe the current implementation; use `docs/design/<version>/` for product goals and module boundaries.

## Update Policy

- `docs/code/` is intentionally unversioned and always tracks the current repository implementation.
- Update the relevant module documents in the same change whenever a feature is completed.
- Product design history is provided by versioned `design` documents; implementation history is provided by Git.

---

*Generated from the current source code; no source files were modified.*
