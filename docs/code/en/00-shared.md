# 00-shared — Shared Runtime Foundation

This module is the common foundation used by the rest of the project.

## What It Does

- Loads settings, environment variables, and runtime configuration.
- Manages database sessions, migrations, transactions, and test isolation.
- Provides provider abstractions, registries, secret storage, and health checks.
- Records audit events, snapshots, logs, metrics, degradation state, and worker state.

## How It Runs

```text
app startup
  -> load settings
  -> initialize database and providers
  -> register API / worker dependencies
  -> record logs, metrics, and audit while tasks run
```

Business modules should not reimplement connection handling, secrets, logs, or audit. They use this shared layer.

## Main Entry Points

- `src/margin/settings.py`
- `src/margin/storage/`
- `src/margin/core/`
- `src/margin/api/`
- `src/margin/worker.py`

## Who Uses It

Data, Agent, Dashboard, API, Worker, and deployment code all depend on this module.
