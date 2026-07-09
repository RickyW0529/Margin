# 01-data_provider — Data Access And Quality

This module turns external market data into internal, traceable, point-in-time-safe data.

## What It Does

- Connects to Tushare / AKShare and other providers.
- Stores raw responses, request parameters, fetch time, and source metadata.
- Standardizes fields and runs schema, key, date, and quality checks.
- Publishes market, financial, valuation, index-member, and suspension data.
- Provides the 20-year backfill control plane: campaign, endpoint plan, partitions, dry-run executor, quality report, and publish guard.

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

The 20-year backfill starts at `2006-01-01` on full calendar-year boundaries. CLI entry:

```bash
python -m margin.cli.backfill init --years 20 --start-date 2006-01-01 --end-date auto
```

## Main Entry Points

- `src/margin/data/providers/`
- `src/margin/data/tushare_query.py`
- `src/margin/data/tushare_quality.py`
- `src/margin/data/tushare_warehouse.py`
- `src/margin/data/requirements.py`
- `src/margin/data/backfill/`
- `src/margin/cli/backfill.py`
- `scripts/run_tushare_backfill.py`

## Who Uses It

`11-valuation_discovery` consumes this data to build pools and features. Upper layers read the derived Mart output.
