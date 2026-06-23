# 11 valuation_discovery — Universe and Valuation Discovery

## Overview

`src/margin/valuation_discovery/` implements the v0.2 universe, quant screening, news-target selection, industry valuation, confidence calibration, effective assessment pointer, and refresh orchestration flow. It consumes frozen warehouse inputs and strategy scopes only; it does not call AKShare, Tushare, Tavily, LLMs, or trading APIs directly.

## Data Model and Migrations

| Table | Purpose |
|-------|---------|
| `universe_definitions` / `universe_versions` / `universe_memberships` / `universe_snapshots` | Built-in and future custom universes with valid time and system time. |
| `quant_input_snapshots` / `quant_input_snapshot_facts` | The only quant input contract, including scope, universe, indicators, fact lineage, PIT, freshness, and quality flags. |
| `quant_screen_runs` / `quant_screen_results` / `quant_factor_values` | Quant runs, per-security results, factor-group values, ranks, and reason summaries. |
| `valuation_assessments` / `confidence_components` / `effective_assessment_pointers` | Valuation conclusions, confidence components, and current effective assessment pointers. |
| `valuation_refresh_runs` / `valuation_refresh_steps` / `research_refresh_events` / `research_context_snapshots` | Refresh runs, step state, events, and research context snapshots. |

Migrations: `20260622_0021` through `20260622_0024`.

## Key Code

| File | Main objects | Purpose |
|------|--------------|---------|
| `models.py` | `UniverseMembership`, `QuantInputSnapshot`, `QuantRun`, `QuantResult`, `NewsTarget`, `EffectiveAssessmentPointer` | Immutable domain records. |
| `universe.py` | `UniverseResolver` | Resolves `CSI300`, `CSI500`, and `ALL_A` by business and system time. |
| `scope.py` / `quant_input.py` | `ScopeBinding`, `QuantInputSnapshotBuilder` | Freezes user-visible and quant-required indicators into PIT input snapshots. |
| `quant/filters.py` | `HardFilterEngine` | Structured hard filters for ST, suspension, listing age, liquidity, missing financials, losses, debt, goodwill, cashflow, and audit opinion. |
| `quant/scoring.py` / `quant/service.py` | `FactorScorer`, `QuantService` | Industry normalization, weighted factor scoring, status/guardrails, ranks, and persistence. |
| `news_targets.py` | `NewsTargetSelector` | Includes all PASS and strategy-allowed NEAR_THRESHOLD names; no top-N truncation. |
| `valuation.py` | `IndustryValuationRegistry` | Bank, insurance, cyclic resource, consumer/manufacturing, growth/tech, and utilities valuation families. |
| `confidence.py` | `ConfidenceCalibrator` | Deterministic confidence calibration; LLM confidence is not accepted as an input. |
| `assessments.py` | `EffectiveAssessmentService` | Deferred/abstained reviews keep the prior assessment; update/invalidate outcomes point to new assessments. |
| `orchestrator.py` / `service.py` | `ValuationDiscoveryOrchestrator`, `ValuationDiscoveryService` | 12-step refresh orchestration, idempotent start, and explicit failed/waiting/skipped semantics. |

## FastAPI Endpoint

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/v1/valuation-discovery/refreshes` | Starts a valuation discovery refresh. Requires local admin auth, CSRF, and `Idempotency-Key`; returns `202` and `run_id`. If the service is not configured, it fails closed with `503`. |

## Smoke

```bash
python scripts/smoke_valuation_discovery_p0.py \
  --scope-version-id scope-active \
  --decision-at 2026-06-22T00:00:00Z \
  --cross-section-csv /path/to/real_warehouse_cross_section.csv

python scripts/smoke_valuation_discovery_p1.py \
  --scope-version-id scope-active \
  --decision-at 2026-06-22T00:00:00Z \
  --api-url http://127.0.0.1:8000
```

The smoke scripts do not generate fake data. Missing real snapshots, cross-sections, API access, or secrets are reported as explicit `external_blocker` values.

## Cross-Module Notes

- Reads: canonical/fact lineage warehouse data, strategy scopes, and module 10 orchestration primitives.
- Writes: quant candidates, NewsTargets, valuation conclusions, effective pointers, and API-visible run IDs.
- Boundary: quant code does not call external providers; news, indexing, RAG, and AI are delegated to their own module services.
