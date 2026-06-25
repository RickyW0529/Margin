# 11 valuation_discovery — Universe and Valuation Discovery

## Overview

`src/margin/valuation_discovery/` implements the v0.2/v0.3 universe, quant screening, fourth-layer Quant Feature Mart / Analysis Mart, news-target selection, industry valuation, confidence calibration, effective assessment pointer, and refresh orchestration flow. It consumes frozen warehouse inputs and strategy scopes only; it does not call AKShare, Tushare, Tavily, LLMs, or trading APIs directly.

In v0.3, `ALL_A` / `ALL_A_NON_ST` scopes prefer the latest data-layer `company_pool_snapshots` via `SQLAlchemyScopeBindingProvider` instead of static universe memberships. The company pool excludes ST, delisting-transition names, future listings, and delisted securities.

The quant service now supports versioned manual-pool strategy metadata. When `QuantInputSnapshot.quant_feature_set.metadata.quant_strategy.thresholds.presets` provides factor weights, `QuantService` uses `manual_all_a_score` as the real `QuantResult.final_score` input for ranks and screening status. `theme_hotness` is a confirmed theme/industry-hotness bonus sourced from PIT-safe cross-section fields `theme_hot_score`, `theme_member_confidence`, and `theme_signal_confirmed`; unconfirmed signals and non-members receive no bonus. The compatibility path without versioned strategy metadata still uses the legacy five-group `FactorScorer.combine()` score.

v0.3 adds fourth-layer marts. Third-layer canonical data is first materialized by the ETL pipeline into `quant_feature_snapshots` / `quant_feature_rows`, and quant reads only those fourth-layer feature snapshots. Quant results are then published through ETL into `analysis_snapshots`, `analysis_metrics`, `analysis_findings`, and `analysis_evidence_links`. This layer serves Quant, dashboards, and LangGraph scoped read tools with structured metrics, findings, quality flags, input/result hashes, and lineage so the AI flow does not recompute the same indicators from lower layers.

## Data Model and Migrations

| Table | Purpose |
|-------|---------|
| `company_pool_snapshots` / `company_pool_members` | v0.3 materialized non-ST/non-delisting All-A company pool consumed by `ALL_A_NON_ST` scopes. |
| `quant_input_snapshots` / `quant_input_snapshot_facts` | The only quant input contract, including scope, universe, indicators, fourth-layer `feature_snapshot_id`, fact lineage, PIT, freshness, and quality flags. |
| `quant_feature_snapshots` | Fourth-layer quant feature snapshots by scope/universe/decision/trading date, storing third-layer ETL input hash, feature columns, lineage summary, quality flags, and row count. |
| `quant_feature_rows` | Fourth-layer per-security quant feature rows with directly consumable fields, source refs, and row-level quality flags such as ST or stale/suspended market data. |
| `quant_screen_runs` / `quant_screen_results` / `quant_factor_values` | Quant runs, per-security results, factor-group values, ranks, and reason summaries. |
| `analysis_snapshots` | Fourth-layer per-security analysis snapshots binding security/scope/decision time, quant run/result, QuantInput, strategy versions, input/result hashes, summaries, and quality flags. |
| `analysis_metrics` | Fourth-layer structured metrics such as final score, factor scores, ranks, percentiles, data-quality indicators, and review flags. |
| `analysis_findings` | Fourth-layer readable findings with screening outcomes, positive/negative factors, risk or missing-data reasons, severity, confidence, and evidence references. |
| `analysis_evidence_links` | Fourth-layer lineage edges from snapshots/metrics/findings to quant results, QuantInput, canonical facts, Evidence, or future ML feature runs. |
| `valuation_assessments` / `effective_assessment_pointers` | Valuation conclusions and current effective assessment pointers. |
| `research_context_snapshots` | Frozen research-context snapshots consumed by AI review. |

Migrations: `20260622_0021` through `20260622_0024`, v0.3 source/company-pool/quant-history-index migrations `20260623_0036` through `20260624_0041`, Analysis Mart migration `20260624_0042_analysis_mart.py`, Quant Feature Mart migration `20260625_0043_quant_feature_mart.py`, and dead-table cleanup migration `20260625_0044_remove_dead_tables.py`.

## Key Code

| File | Main objects | Purpose |
|------|--------------|---------|
| `models.py` | `UniverseMembership`, `QuantInputSnapshot`, `QuantRun`, `QuantResult`, `NewsTarget`, `EffectiveAssessmentPointer` | Immutable domain records. |
| `universe.py` | `UniverseResolver` | Resolves `CSI300`, `CSI500`, and `ALL_A` by business and system time. |
| `scope.py` / `quant_input.py` | `ScopeBinding`, `QuantInputSnapshotBuilder` | Freezes user-visible and quant-required indicators into PIT input snapshots. |
| `quant_adapter.py` | `SQLAlchemyScopeBindingProvider`, `WarehouseFactAdapter`, `build_cross_section_loader`, `QuantAdapter` | Connects strategy scopes, data-layer company pools, warehouse canonical/history reads, fourth-layer feature ETL, and quant service execution. Historical market reads cap at the latest 260 PIT points per security/indicator for stable full-universe runs. |
| `quant/filters.py` | `HardFilterEngine` | Structured hard filters for ST, suspension, listing age, liquidity, missing financials, losses, debt, goodwill, cashflow, and audit opinion. |
| `quant/scoring.py` / `quant/service.py` | `FactorScorer`, `QuantService` | Industry normalization, weighted factor scoring, versioned manual-pool final score, status/guardrails, ranks, and persistence. |
| `quant/manual_all_a.py` / `quant/theme_tilt.py` | `score_manual_all_a`, `score_theme_components`, `confirmation_states` | Manual three-pool quant scoring, confirmed theme/industry-hotness bonus, and theme entry/exit confirmation. |
| `etl.py` | `SQLAlchemyQuantFeatureMartETLPipeline`, `QuantFeatureMartETLPipeline`, `AnalysisResultMartETLPipeline`, `build_feature_mart_cross_section_loader` | The v0.3 ETL management layer; it coordinates third-layer-to-feature-mart publishing, quant reads from fourth-layer features, and quant-result publishing back to Analysis Mart. |
| `analysis_mart.py` | `AnalysisMartPublisher`, `SQLAlchemyAnalysisMartRepository`, `MemoryAnalysisMartRepository`, `QuantFeatureSnapshot`, `AnalysisSnapshot`, `AnalysisMetric`, `AnalysisFinding` | Fourth-layer feature and analysis-result publishing/reads; same-input replay is idempotent and conflicting replay is rejected. |
| `news_targets.py` | `NewsTargetSelector` | Includes all PASS and strategy-allowed NEAR_THRESHOLD names; no top-N truncation. |
| `valuation.py` | `IndustryValuationRegistry` | Bank, insurance, cyclic resource, consumer/manufacturing, growth/tech, and utilities valuation families. |
| `confidence.py` | `ConfidenceCalibrator` | Deterministic confidence calibration; LLM confidence is not accepted as an input. |
| `assessments.py` | `EffectiveAssessmentService` | Deferred/abstained reviews keep the prior assessment; update/invalidate outcomes point to new assessments. |
| `orchestrator.py` / `service.py` | `ValuationDiscoveryOrchestrator`, `ValuationDiscoveryService` | 12-step refresh orchestration, idempotent start, and explicit failed/waiting/skipped semantics. |

## Fourth-Layer Marts and ETL

Publishing path:

```text
third-layer canonical/company pool/history
  -> SQLAlchemyQuantFeatureMartETLPipeline.materialize(...)
  -> quant_feature_snapshots / quant_feature_rows
  -> QuantService reads only the fourth-layer feature_snapshot_id cross-section
  -> QuantResult + quant run lineage
  -> AnalysisResultMartETLPipeline.publish_quant_result(...)
  -> analysis_snapshots / analysis_metrics / analysis_findings / analysis_evidence_links
  -> ResearchContext payload.analysis_snapshot_id / analysis_summary
  -> module 06 analysis_* scoped read tools
```

Transaction boundaries:

- `SQLAlchemyQuantFeatureMartETLPipeline` writes the `feature_snapshot_id`-bound `quant_input_snapshots`, `quant_input_snapshot_facts`, `quant_feature_snapshots`, and `quant_feature_rows` in one database transaction;
- `AnalysisMartRepository.upsert_bundle()` writes `analysis_snapshots`, metrics, findings, and links in one transaction;
- any child-row conflict or write failure rolls back the current ETL publication, so no header-only or partial-row dirty data remains;
- when feature ETL is configured, `QuantAdapter.build_input()` materializes fourth-layer features before passing the bound `QuantInputSnapshot` into quant execution.

`AnalysisMartPublisher` currently derives:

- snapshot summary: `screening_status`, `data_status`, `research_guardrail`, `review_required`, ranks, major reasons, risks, and missing fields;
- metrics: `final_score`, `quality_score`, `value_score`, `growth_score`, `momentum_score`, `risk_score`, ranks, and review/data-quality indicators;
- findings: one `quant_screening` finding with screening state, data state, risk flags, positive/negative factors, and confidence;
- evidence links: lineage to `quant_screen_results`, `quant_screen_runs`, and `quant_input_snapshots`.

Repository behavior:

- `upsert_bundle()` writes the snapshot, metrics, findings, and links in one transaction;
- identical primary keys with identical content are idempotent replays;
- identical primary keys with different content/hash are rejected to avoid overwriting historical analysis;
- `latest_snapshot(security_id, scope_version_id, as_of)` returns the visible snapshot for a decision time;
- `list_metrics()`, `list_findings()`, and `list_evidence_links()` serve dashboards and AI tools.

`ResearchContextBuilderAdapter` publishes Analysis Mart when a repository is available and stores `analysis_snapshot_id` plus `analysis_summary` in the frozen payload. Without a repository it keeps the compatibility path and does not block offline usage.

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
- Writes: quant candidates, Analysis Mart snapshots/metrics/findings/lineage, NewsTargets, valuation conclusions, effective pointers, and API-visible run IDs.
- Boundary: quant code does not call external providers; Analysis Mart is derived only from the unique serving layer, quant results, and controlled evidence links; news, indexing, RAG, and AI are delegated to their own module services.
