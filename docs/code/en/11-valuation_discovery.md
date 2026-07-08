# 11-valuation_discovery — Company Pools, Quant, And Analysis Mart

This module turns trusted data into stock candidates and analysis output.

## What It Does

- Builds company-pool snapshots and excludes ST, delisting, future-listed, or non-tradeable securities.
- Builds quant features from PIT-safe data.
- Runs ML / quant screening strategies.
- Publishes scores, explanations, risks, and lineage to Analysis Mart.

## How It Runs

```text
company pool snapshot
  -> Quant Feature Mart
  -> ML / quant strategy
  -> Analysis Mart
  -> Agent review
  -> Dashboard recommendations
```

It is the bridge between trusted data and Agent / Dashboard output. Upper layers should not read raw financial or market data directly.

## Main Entry Points

- `src/margin/valuation_discovery/`
- `src/margin/valuation_discovery/quant/`
- `src/margin/valuation_discovery/quant_adapter.py`

## Who Uses It

Agents read Analysis Mart for review. Dashboard shows recommendations, scores, and risks.
