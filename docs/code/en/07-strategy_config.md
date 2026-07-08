# 07-strategy_config — Strategy And Provider Configuration

This module tells the system which data, models, scope, strategy, and prompts to use.

## What It Does

- Manages provider configuration and secret versions.
- Manages research scope, company pools, metric views, and strategy templates.
- Manages prompts, custom configuration, version lifecycle, and active state.
- Manages runtime zipper-table configuration such as Agent flows and QuantAgent profiles.
- Runs validation, provider health checks, and fail-closed degradation.

## How It Runs

```text
user saves settings
  -> write config version
  -> provider health check
  -> activate usable config
  -> research run resolves decision_at-safe config through one resolver
```

Secrets are write-only in the UI. Tasks depending on unavailable providers should fail clearly instead of pretending to succeed.
Runtime configuration is not stored in one generic table: each domain has its own version table, and a run records only the resolved version references.

## Main Entry Points

- `src/margin/strategy/`
- `src/margin/config_runtime/`
- `src/margin/core/secret_store.py`
- `src/margin/api/routes/strategy*.py`
- `web/components/provider-settings-panel.tsx`

## Who Uses It

Data providers, Agents, Dashboard, and Worker schedules all read active configuration from here.
