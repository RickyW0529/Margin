"""Health, readiness and degradation endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Response, status

from margin.core.provider import HealthCheckResult, ProviderStatus
from margin.settings import get_settings
from margin.storage.database import DatabaseSettings, create_database_engine

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Simple liveness probe."""
    return {"status": "ok"}


@router.get("/health/ready")
def ready() -> Response:
    """Readiness probe: database must be reachable."""
    settings = get_settings()
    try:
        engine = create_database_engine(
            DatabaseSettings(url=str(settings.database_url))
        )
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        return Response(
            content='{"status":"ready"}',
            media_type="application/json",
            status_code=status.HTTP_200_OK,
        )
    except Exception as exc:  # noqa: BLE001
        return Response(
            content=f'{{"status":"not_ready","detail":"{exc}"}}',
            media_type="application/json",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


@router.get("/health/degraded")
def degraded() -> dict[str, object]:
    """Return true if database is not ready or any provider is degraded."""
    settings = get_settings()
    degraded_providers: list[HealthCheckResult] = []
    try:
        engine = create_database_engine(
            DatabaseSettings(url=str(settings.database_url))
        )
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
    except Exception as exc:  # noqa: BLE001
        degraded_providers.append(
            HealthCheckResult(
                provider_name="database",
                status=ProviderStatus.UNHEALTHY,
                checked_at=datetime.now(UTC),
                message=str(exc),
            )
        )
    return {
        "degraded": len(degraded_providers) > 0,
        "degraded_count": len(degraded_providers),
        "providers": [r.model_dump() for r in degraded_providers],
        "service": settings.service_name,
        "version": settings.service_version,
    }
