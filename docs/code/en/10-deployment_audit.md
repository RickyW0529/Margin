# 10-deployment_audit — Deployment, Audit, And Observability

This module makes the system runnable, inspectable, degradable, and auditable.

## What It Does

- Provides Docker, Compose, migration, bootstrap, and smoke scripts.
- Exposes health checks, Prometheus metrics, and structured logs.
- Stores audit records, snapshots, task state, and degradation reasons.
- Reports explicit status when providers, config, or tasks fail.
- Adds v1 runtime/control-plane tables for agent tasks/artifacts/context, tool audit, prompt render history, backfill campaigns, outbox, DLQ, and freshness state.

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
- `src/margin/api/routes/health.py`
- `/metrics`
- `alembic/versions/20260708_0053` through `20260708_0057`
- `src/margin/api/routes/backfill.py`, `freshness.py`, `tool_audit.py`

## Who Uses It

Developers, CI, deployments, Agents, and Dashboard use it to understand runtime state.
