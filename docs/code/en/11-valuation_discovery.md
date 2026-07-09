# 11-valuation_discovery — Company Pools, Quant, And Analysis Mart

This module turns trusted data into stock candidates and analysis output.

## What It Does

- Builds company-pool snapshots and excludes ST, delisting, future-listed, or non-tradeable securities.
- Builds quant features from PIT-safe data.
- Runs ML / quant screening strategies.
- Publishes scores, explanations, risks, and lineage to Analysis Mart.
- Mirrors outputs into normalized Mart tables: `mart.factor_panel`, `mart.quant_candidate_mart`, `mart.stock_analysis_mart`, plus `app.company_profile_page_v1` for API/UI serving.

## How It Runs

```text
company pool snapshot
  -> Quant Feature Mart
  -> ML / quant strategy
  -> mart / app serving
  -> Agent review
  -> Dashboard recommendations
```

It is the bridge between trusted data and Agent / Dashboard output. Upper layers should not read raw financial or market data directly.

## Main Entry Points

- `src/margin/valuation_discovery/`
- `src/margin/valuation_discovery/quant/`
- `src/margin/valuation_discovery/quant_adapter.py`
- `alembic/versions/20260709_0059_complete_v1_warehouse_layers.py`

## Who Uses It

Agents read Analysis Mart for review. Dashboard shows recommendations, scores, and risks.
