"""API coverage for durable data-sync planning."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from margin.api.dependencies import get_data_policy_service, get_data_warehouse_stack
from margin.api.main import create_app
from margin.data.db_models import DataSyncWorkItemRow
from margin.data.ingestion import DataWarehouseIngestionStack
from margin.data.policy import (
    DataAcquisitionPolicyService,
    MemoryDataAcquisitionPolicyRepository,
)
from margin.settings import get_settings
from margin.storage.base import Base
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)


def test_default_data_sync_request_creates_executable_work_items(
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Test that a default API request never creates a zero-work pending run."""
    monkeypatch.setenv("MARGIN_ADMIN_API_TOKEN", "admin-test-token")
    monkeypatch.setenv("MARGIN_CSRF_TOKEN", "valid")
    get_settings.cache_clear()
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    stack = DataWarehouseIngestionStack(
        session_factory=session_factory,
        snapshot_root=tmp_path,
        default_provider="tushare",
    )
    app = create_app()
    app.dependency_overrides[get_data_warehouse_stack] = lambda: stack
    policy_service = DataAcquisitionPolicyService(
        MemoryDataAcquisitionPolicyRepository()
    )
    active_policy = policy_service.create(
        rolling_window_months=24,
        actor_id="local-admin",
        idempotency_key="data-sync-policy-create",
    )
    policy_service.activate(
        active_policy.version_id,
        actor_id="local-admin",
        idempotency_key="data-sync-policy-activate",
    )
    app.dependency_overrides[get_data_policy_service] = lambda: policy_service

    response = TestClient(app).post(
        "/api/v1/data-sync",
        json={"requested_by": "api-test"},
        headers={
            "Authorization": "Bearer admin-test-token",
            "X-CSRF-Token": "valid",
            "Idempotency-Key": "data-sync-api-test",
        },
    )

    assert response.status_code == 202
    run_id = response.json()["sync_run_id"]
    with session_factory() as session:
        work_item_count = session.scalar(
            select(func.count())
            .select_from(DataSyncWorkItemRow)
            .where(DataSyncWorkItemRow.run_id == run_id)
        )
    assert work_item_count == 7
    run = stack.sync_repository.get_run(run_id)
    assert run is not None
    assert run.request.data_policy_version_id == active_policy.version_id
    assert run.request.window_start is not None
    assert run.request.window_end is not None
    assert run.request.backfill_start == run.request.window_start
    assert run.request.backfill_end == run.request.window_end
    engine.dispose()


def test_data_sync_rejects_unauthenticated_frontend_write() -> None:
    """Test that manual sync is a protected mutation, not a public trigger."""
    response = TestClient(create_app()).post(
        "/api/v1/data-sync",
        json={"requested_by": "anonymous"},
        headers={"Idempotency-Key": "anonymous-sync"},
    )

    assert response.status_code in {401, 503}
