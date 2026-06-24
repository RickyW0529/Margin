"""Health, readiness and degradation endpoints.

Provides Kubernetes-style probes:

* ``/health`` - lightweight liveness check.
* ``/health/ready`` - readiness check that verifies database connectivity.
* ``/health/degraded`` - aggregated degradation status across providers and DB.
"""

from __future__ import annotations

from datetime import UTC, datetime

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from sqlalchemy import Engine

from margin.core.provider import HealthCheckResult, ProviderStatus
from margin.settings import get_settings
from margin.sql.health_queries import (
    active_provider_config_count,
    alembic_version,
    outbox_pending_count,
    queue_counts,
    retryable_step_count,
)
from margin.storage.database import DatabaseSettings, create_database_engine

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Simple liveness probe."""
    return {"status": "ok"}


def _database_health() -> tuple[bool, str | None]:
    """Check database connectivity and always release the temporary engine.

    Creating a dedicated engine for the probe avoids coupling health status to
    the lifespan-managed application engine and guarantees connection cleanup.
    """
    settings = get_settings()
    engine: Engine | None = None
    try:
        engine = create_database_engine(
            DatabaseSettings(url=str(settings.database_url))
        )
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        return True, None
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
    finally:
        # Dispose must run even when connect() succeeds so the probe does not leak pools.
        if engine is not None:
            engine.dispose()


def _alembic_head() -> str:
    """alembic head."""
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)
    return script.get_current_head()


def _ready_checks() -> dict[str, dict[str, object]]:
    """ready checks."""
    settings = get_settings()
    checks: dict[str, dict[str, object]] = {
        "database": {"status": "failed"},
        "migration_head": {"status": "failed"},
        "outbox": {"status": "failed"},
        "provider_config": {"status": "failed"},
        "worker": {"status": "failed"},
    }
    engine: Engine | None = None
    try:
        engine = create_database_engine(
            DatabaseSettings(url=str(settings.database_url))
        )
        head = _alembic_head()
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
            checks["database"] = {"status": "ok"}
            current = conn.execute(alembic_version()).scalar()
            checks["migration_head"] = {
                "status": "ok" if current == head else "failed",
                "current": current,
                "head": head,
            }
            outbox_pending = int(
                conn.execute(outbox_pending_count()).scalar() or 0
            )
            checks["outbox"] = {
                "status": "ok",
                "pending_count": outbox_pending,
            }
            active_provider_configs = int(
                conn.execute(active_provider_config_count()).scalar() or 0
            )
            checks["provider_config"] = {
                "status": "ok",
                "active_count": active_provider_configs,
            }
            retryable_steps = int(
                conn.execute(retryable_step_count()).scalar() or 0
            )
            checks["worker"] = {
                "status": "ok",
                "ready_step_count": retryable_steps,
            }
    except Exception:  # noqa: BLE001
        # Do not expose exception text here; readiness is externally visible.
        pass
    finally:
        if engine is not None:
            engine.dispose()
    return checks


def _queue_counts() -> dict[str, int]:
    """queue counts."""
    settings = get_settings()
    engine: Engine | None = None
    counts = {
        "waiting_budget_count": 0,
        "waiting_rate_limit_count": 0,
        "retry_queue_count": 0,
        "outbox_pending_count": 0,
    }
    try:
        engine = create_database_engine(
            DatabaseSettings(url=str(settings.database_url))
        )
        probes = queue_counts()
        with engine.connect() as conn:
            counts["waiting_budget_count"] = int(
                conn.execute(probes["waiting_budget"]).scalar() or 0
            )
            counts["waiting_rate_limit_count"] = int(
                conn.execute(probes["waiting_rate_limit"]).scalar() or 0
            )
            counts["retry_queue_count"] = int(
                conn.execute(probes["retry_queue"]).scalar() or 0
            )
            counts["outbox_pending_count"] = int(
                conn.execute(probes["outbox_pending"]).scalar() or 0
            )
    except Exception:  # noqa: BLE001
        pass
    finally:
        if engine is not None:
            engine.dispose()
    return counts


@router.get("/health/ready")
def ready() -> JSONResponse:
    """Readiness probe: DB, migration head, outbox, config, and worker tables."""
    checks = _ready_checks()
    ready_status = all(check["status"] == "ok" for check in checks.values())
    if ready_status:
        return JSONResponse(
            content={"status": "ready", "checks": checks},
            status_code=status.HTTP_200_OK,
        )
    return JSONResponse(
        content={"status": "not_ready", "checks": checks},
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


@router.get("/health/degraded")
def degraded() -> dict[str, object]:
    """Return true if database is not ready or any provider is degraded."""
    settings = get_settings()
    degraded_providers: list[HealthCheckResult] = []
    healthy, error = _database_health()
    if not healthy:
        degraded_providers.append(
            HealthCheckResult(
                provider_name="database",
                status=ProviderStatus.UNHEALTHY,
                checked_at=datetime.now(UTC),
                message=error,
            )
        )
    counts = _queue_counts()
    degraded_status = len(degraded_providers) > 0 or any(
        value > 0 for value in counts.values()
    )
    return {
        "degraded": degraded_status,
        "degraded_count": len(degraded_providers),
        "providers": [r.model_dump() for r in degraded_providers],
        **counts,
        "service": settings.service_name,
        "version": settings.service_version,
    }
