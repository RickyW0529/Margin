"""Health, readiness and degradation endpoints.

Provides Kubernetes-style probes:

* ``/health`` - lightweight liveness check.
* ``/health/ready`` - readiness check that verifies database connectivity.
* ``/health/degraded`` - aggregated degradation status across providers and DB.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from sqlalchemy import Engine

from margin.core.provider import HealthCheckResult, ProviderStatus
from margin.settings import get_settings
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


@router.get("/health/ready")
def ready() -> JSONResponse:
    """Readiness probe: database must be reachable."""
    healthy, _ = _database_health()
    if healthy:
        return JSONResponse(
            content={"status": "ready"},
            status_code=status.HTTP_200_OK,
        )
    return JSONResponse(
        content={"status": "not_ready"},
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
    return {
        "degraded": len(degraded_providers) > 0,
        "degraded_count": len(degraded_providers),
        "providers": [r.model_dump() for r in degraded_providers],
        "service": settings.service_name,
        "version": settings.service_version,
    }
