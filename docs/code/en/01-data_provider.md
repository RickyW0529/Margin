# 01-data_provider — Data Access And Quality

This module turns external market data into internal, traceable, point-in-time-safe data.

## What It Does

- Connects to Tushare / AKShare and other providers.
- Stores raw responses, request parameters, fetch time, and source metadata.
- Standardizes fields and runs schema, key, date, and quality checks.
- Publishes market, financial, valuation, index-member, and suspension data.

## How It Runs

```text
provider config
  -> fetch raw data
  -> save landing/raw records
  -> quality gate
  -> warehouse publisher
  -> PIT / canonical data for quant
```

Quant, Agent, and Dashboard code should read published data, not call external providers directly.

## Main Entry Points

- `src/margin/data/providers/`
- `src/margin/data/tushare_query.py`
- `src/margin/data/tushare_quality.py`
- `src/margin/data/tushare_warehouse.py`
- `src/margin/data/requirements.py`
- `scripts/run_tushare_backfill.py`

## Who Uses It

`11-valuation_discovery` consumes this data to build pools and features. Upper layers read the derived Mart output.
