# 01-data_provider — Data Access And Quality

This module turns external market data into internal, traceable, point-in-time-safe data.

## What It Does

- Connects to Tushare / AKShare and other providers.
- Stores raw responses, request parameters, fetch time, and source metadata.
- Standardizes fields and runs schema, key, date, and quality checks.
- Publishes market, financial, valuation, index-member, and suspension data.
- Uses `20260709_0059` to migrate legacy `public` data non-destructively into `raw_meta`, `source_*`, `vault`, `mart_dw`, `mart`, and `app` layers.
- Provides the 20-year backfill control plane: campaign, endpoint plan, partitions, dry-run executor, quality report, and publish guard. The API persists campaign, partition, quality report, and idempotency records to `ops.*` / `platform.idempotency_keys` by default.

## How It Runs

```text
provider config
  -> fetch raw data
  -> save landing/raw records
  -> quality gate
  -> raw_meta / source_* / vault
  -> PIT / mart_dw / mart
  -> app serving layer
```

Quant, Agent, and Dashboard code should read published data, not call external providers directly.
Legacy `public` tables remain as a compatibility layer; new work should use the layered warehouse.

The 20-year backfill starts at `2006-01-01` on full calendar-year boundaries. CLI entry:

```bash
python -m margin.cli.backfill init --years 20 --start-date 2006-01-01 --end-date auto
```

The current executor is a dry-run metadata path and does not fetch live provider data directly; live fetch and PIT promotion must be wired through deterministic data/backfill tools.

## Main Entry Points

- `src/margin/data/providers/`
- `src/margin/data/tushare_query.py`
- `src/margin/data/tushare_quality.py`
- `src/margin/data/tushare_warehouse.py`
- `src/margin/data/requirements.py`
- `src/margin/data/backfill/`
- `src/margin/data/backfill/repository.py`
- `src/margin/cli/backfill.py`
- `scripts/run_tushare_backfill.py`
- `alembic/versions/20260708_0053` through `20260709_0059`

## Who Uses It

`11-valuation_discovery` consumes this data to build pools and features. Upper layers read the derived Mart output.
