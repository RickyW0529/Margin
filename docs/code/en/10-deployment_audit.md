# 10-deployment_audit — Deployment, Audit, And Observability

This module makes the system runnable, inspectable, degradable, and auditable.

## What It Does

- Provides Docker, Compose, migration, bootstrap, and smoke scripts.
- Exposes health checks, Prometheus metrics, and structured logs.
- Stores audit records, snapshots, task state, and degradation reasons.
- Reports explicit status when providers, config, or tasks fail.
- Keeps the active runtime tables for orchestration, outbox, audit, Agent chat, versioned config, data sync state, Dashboard state, and formal `platform.*` / `ops.*` records.
- Uses `20260709_0058` to remove unused v1 draft control-plane tables.
- Uses `20260709_0059` to complete the PIT warehouse layers and migrate legacy table data into the new layers non-destructively.
- Uses `20260709_0063` to reintroduce formal platform/ops tables for idempotency, runtime environments, config snapshots, outbox, dead letters, backfill, health, and freshness.

## How It Runs

```text
deployment startup
  -> migrations
  -> bootstrap configuration
  -> api / worker / web startup
  -> health / metrics / audit records
```

It does not produce recommendations, but it makes failures diagnosable.

## Main Entry Points

- `Dockerfile`, `web/Dockerfile`, `docker-compose.yml`
- `scripts/`
- `src/margin/core/`
- `src/margin/platform_runtime/`
- `src/margin/api/routes/health.py`
- `/metrics`
- `alembic/versions/20260708_0053` through `20260709_0063`
- `src/margin/api/routes/backfill.py`, `freshness.py`, `tool_audit.py`

## Who Uses It

Developers, CI, deployments, Agents, and Dashboard use it to understand runtime state.
