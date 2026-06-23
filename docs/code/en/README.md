# Margin Current Code Documentation Index (English)

This directory contains function-level documentation for the current Margin implementation. It covers backend Python modules, FastAPI endpoints, Next.js pages, React components, and deployment/observability configuration.

## Directory Structure

```
docs/code/en/
├── README.md                         This file
├── 00-shared.md                      Shared and core cross-cutting components
├── 01-data_provider.md               Data Provider module
├── 03-filing_websearch.md            Filing & WebSearch module
├── 04-text_indexing.md               Text Indexing module
├── 05-rag_evidence.md                RAG Evidence module
├── 06-multi_agent_research.md        Multi-Agent Research module
├── 07-strategy_config.md             Strategy Configuration module
├── 08-research_candidate_dashboard.md Research Candidate Dashboard module
├── 10-deployment_audit.md            Deployment & Audit module
└── 11-valuation_discovery.md         Universe & Valuation Discovery module
```

## Module Index

| ID | Module (slug) | Chinese name | Documentation | Source paths |
|----|---------------|--------------|---------------|--------------|
| 00 | shared | Shared / core cross-cutting | [00-shared.md](./00-shared.md) | `src/margin/settings.py`, `src/margin/worker.py`, `src/margin/storage/`, `src/margin/api/`, `src/margin/core/provider.py`, `src/margin/core/registry.py`, `src/margin/core/resilience.py`, `src/margin/core/secret.py` |
| 01 | data_provider | Data Provider | [01-data_provider.md](./01-data_provider.md) | `src/margin/data/`, `src/margin/core/provider.py`, `src/margin/core/registry.py` |
| 03 | filing_websearch | Filing & WebSearch | [03-filing_websearch.md](./03-filing_websearch.md) | `src/margin/news/` |
| 04 | text_indexing | Text Indexing | [04-text_indexing.md](./04-text_indexing.md) | `src/margin/vector/` |
| 05 | rag_evidence | RAG Evidence | [05-rag_evidence.md](./05-rag_evidence.md) | `src/margin/evidence/` |
| 06 | multi_agent_research | Multi-Agent Research | [06-multi_agent_research.md](./06-multi_agent_research.md) | `src/margin/research/` |
| 07 | strategy_config | Strategy Configuration | [07-strategy_config.md](./07-strategy_config.md) | `src/margin/strategy/`, `src/margin/core/secret_store.py`, `src/margin/api/routes/strategy.py`, `src/margin/api/routes/strategy_config.py`, `web/components/provider-settings-panel.tsx` |
| 08 | research_candidate_dashboard | Research Candidate Dashboard | [08-research_candidate_dashboard.md](./08-research_candidate_dashboard.md) | `src/margin/dashboard/`, `src/margin/api/routes/dashboard.py`, `src/margin/api/routes/valuation_discovery.py`, `web/app/research/`, `web/app/settings/`, `web/components/research-*.tsx`, `web/components/current-vs-effective-panel.tsx`, `web/components/evidence-locator-list.tsx`, `web/components/read-only-copilot-panel.tsx`, `web/components/provider-settings-panel.tsx` |
| 10 | deployment_audit | Deployment & Audit | [10-deployment_audit.md](./10-deployment_audit.md) | `src/margin/core/` (audit, snapshot, degradation, logging, metrics, run_states, orchestration, capacity, outbox), `src/margin/api/middleware.py`, `src/margin/api/metrics.py`, `src/margin/api/routes/health.py`, `Dockerfile`, `web/Dockerfile`, `docker-compose.yml`, `.github/workflows/ci.yml`, `scripts/` (migration/worker/smoke), `docker/prometheus.yml`, `docker/grafana/` |
| 11 | valuation_discovery | Universe & Valuation Discovery | [11-valuation_discovery.md](./11-valuation_discovery.md) | `src/margin/valuation_discovery/`, `src/margin/api/routes/valuation_discovery.py`, `scripts/smoke_valuation_discovery_p0.py`, `scripts/smoke_valuation_discovery_p1.py` |

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
- Module IDs 02 and 09 remain reserved for history; their implementations were removed in v0.2, so they have no current code documents.

---

*This index describes the current source tree. Module IDs 02 and 09 are historical reservations whose implementations were removed in v0.2.*
