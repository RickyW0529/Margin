"""API coverage for durable data-sync planning."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from margin.api.dependencies import get_data_warehouse_stack
from margin.api.main import create_app
from margin.data.db_models import DataSyncWorkItemRow
from margin.data.ingestion import DataWarehouseIngestionStack
from margin.storage.base import Base
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)


def test_default_data_sync_request_creates_executable_work_items(
    database_url: str,
    tmp_path,
) -> None:
    """A default API request must never create a zero-work pending run."""
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

    response = TestClient(app).post(
        "/api/v1/data-sync",
        json={"requested_by": "api-test"},
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
    engine.dispose()
