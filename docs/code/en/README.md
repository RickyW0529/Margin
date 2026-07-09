# How The Code Modules Run

A “today’s research” run roughly follows this order. This page only explains how modules work together; detailed APIs and fields live in each numbered module document.

| Order | Module | Runtime Role |
| --- | --- | --- |
| 0 | `00-shared` | Provides database, settings, audit, logging, workers, and shared provider abstractions. |
| 1 | `07-strategy_config` | Reads provider, scope, strategy, and prompt settings for the run. |
| 2 | `01-data_provider` | Fetches and standardizes market, financial, and index-member data; supports 20-year backfill campaigns and quality publish gates. |
| 3 | `11-valuation_discovery` | Builds company pools and quant features, runs ML/quant screening, and publishes Analysis Mart output. |
| 4 | `03-filing_websearch` | Adds filings, news, and WebSearch material for selected candidates, including raw snapshots. |
| 5 | `04-text_indexing` | Parses, chunks, and embeds text so retrieval can find relevant evidence. |
| 6 | `05-rag_evidence` | Turns retrieved material into evidence packages with locators and traceable evidence links. |
| 7 | `06-multi_agent_research` | MainAgent coordinates expert agents to combine quant results, evidence, and risk review. |
| 8 | `08-research_candidate_dashboard` | Shows research candidates, reasons, risks, evidence, detail pages, and Agent progress. |
| 9 | `10-deployment_audit` | Handles deployment, migrations, health checks, metrics, degradation, runtime audit, and safe control-plane APIs. |

## Data Direction

```text
Data Provider
  -> Backfill / PIT warehouse
  -> Quant / Analysis Mart
  -> Evidence / RAG
  -> MainAgent Review
  -> Dashboard
```

Module IDs 02 and 09 are historical reservations; their implementations have been removed.
