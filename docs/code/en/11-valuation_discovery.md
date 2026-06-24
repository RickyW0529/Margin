# 11 valuation_discovery — Universe and Valuation Discovery

## Overview

`src/margin/valuation_discovery/` implements the v0.2/v0.3 universe, quant screening, news-target selection, industry valuation, confidence calibration, effective assessment pointer, and refresh orchestration flow. It consumes frozen warehouse inputs and strategy scopes only; it does not call AKShare, Tushare, Tavily, LLMs, or trading APIs directly.

In v0.3, `ALL_A` / `ALL_A_NON_ST` scopes prefer the latest data-layer `company_pool_snapshots` via `SQLAlchemyScopeBindingProvider` instead of static universe memberships. The company pool excludes ST, delisting-transition names, future listings, and delisted securities.

The quant service now supports versioned manual-pool strategy metadata. When `QuantInputSnapshot.quant_feature_set.metadata.quant_strategy.thresholds.presets` provides factor weights, `QuantService` uses `manual_all_a_score` as the real `QuantResult.final_score` input for ranks and screening status. `theme_hotness` is a confirmed theme/industry-hotness bonus sourced from PIT-safe cross-section fields `theme_hot_score`, `theme_member_confidence`, and `theme_signal_confirmed`; unconfirmed signals and non-members receive no bonus. The compatibility path without versioned strategy metadata still uses the legacy five-group `FactorScorer.combine()` score.

## Data Model and Migrations

| Table | Purpose |
|-------|---------|
| `universe_definitions` / `universe_versions` / `universe_memberships` / `universe_snapshots` | Built-in and future custom universes with valid time and system time. |
| `company_pool_snapshots` / `company_pool_members` | v0.3 materialized non-ST/non-delisting All-A company pool consumed by `ALL_A_NON_ST` scopes. |
| `quant_input_snapshots` / `quant_input_snapshot_facts` | The only quant input contract, including scope, universe, indicators, fact lineage, PIT, freshness, and quality flags. |
| `quant_screen_runs` / `quant_screen_results` / `quant_factor_values` | Quant runs, per-security results, factor-group values, ranks, and reason summaries. |
| `valuation_assessments` / `confidence_components` / `effective_assessment_pointers` | Valuation conclusions, confidence components, and current effective assessment pointers. |
| `valuation_refresh_runs` / `valuation_refresh_steps` / `research_refresh_events` / `research_context_snapshots` | Refresh runs, step state, events, and research context snapshots. |

Migrations: `20260622_0021` through `20260622_0024`, plus v0.3 source/company-pool/quant-history-index migrations `20260623_0036` through `20260624_0041`.

## Key Code

| File | Main objects | Purpose |
|------|--------------|---------|
| `models.py` | `UniverseMembership`, `QuantInputSnapshot`, `QuantRun`, `QuantResult`, `NewsTarget`, `EffectiveAssessmentPointer` | Immutable domain records. |
| `universe.py` | `UniverseResolver` | Resolves `CSI300`, `CSI500`, and `ALL_A` by business and system time. |
| `scope.py` / `quant_input.py` | `ScopeBinding`, `QuantInputSnapshotBuilder` | Freezes user-visible and quant-required indicators into PIT input snapshots. |
| `quant_adapter.py` | `SQLAlchemyScopeBindingProvider`, `WarehouseFactAdapter`, `build_cross_section_loader`, `QuantAdapter` | Connects strategy scopes, data-layer company pools, warehouse canonical/history reads, and quant service execution. Historical market reads cap at the latest 260 PIT points per security/indicator for stable full-universe runs. |
| `quant/filters.py` | `HardFilterEngine` | Structured hard filters for ST, suspension, listing age, liquidity, missing financials, losses, debt, goodwill, cashflow, and audit opinion. |
| `quant/scoring.py` / `quant/service.py` | `FactorScorer`, `QuantService` | Industry normalization, weighted factor scoring, versioned manual-pool final score, status/guardrails, ranks, and persistence. |
| `quant/manual_all_a.py` / `quant/theme_tilt.py` | `score_manual_all_a`, `score_theme_components`, `confirmation_states` | Manual three-pool quant scoring, confirmed theme/industry-hotness bonus, and theme entry/exit confirmation. |
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

## v0.3 Real Quant Output

Latest verified Tushare-backed quant run:

- Company-pool snapshot: `cps_29518c0fec90836c57609b6f1f24`
- Quant run: `qr_df48cd92fdf1424d`
- Decision time: `2026-06-22T16:00:00Z`
- Input companies: 5304
- Quant input: `qis_432bf2fba3e741cb`, `fact_count=76462`, `missing_required=[]`, `data_status=ok`
- Result distribution: 3 `pass`, 54 `near_threshold`, 447 `watchlist`, and 4800 `reject`; 4 rows have `data_status=insufficient`, and 3495 rows require review.
- The theme/industry-hotness final-score path is covered by an in-memory service regression. The distribution below is from the pre-connection warehouse validation run and should be refreshed after rerunning real database quant.

Top pass:

| rank | code | name | final | quality | value | growth | momentum | risk | status |
|---:|---|---|---:|---:|---:|---:|---:|---:|---|
| 1 | 002416.SZ | 爱施德 | 92.50 | 100.00 | 70.00 | 100.00 | 100.00 | 100.00 | pass |
| 2 | 603223.SH | 恒通股份 | 90.50 | 100.00 | 70.00 | 100.00 | 100.00 | 80.00 | pass |
| 3 | 000592.SZ | 平潭发展 | 80.25 | 100.00 | 25.00 | 100.00 | 100.00 | 90.00 | pass |

## Cross-Module Notes

- Reads: canonical/fact lineage warehouse data, strategy scopes, and module 10 orchestration primitives.
- Writes: quant candidates, NewsTargets, valuation conclusions, effective pointers, and API-visible run IDs.
- Boundary: quant code does not call external providers; news, indexing, RAG, and AI are delegated to their own module services.
