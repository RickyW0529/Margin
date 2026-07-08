"""PostgreSQL-backed strategy API integration tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from margin.api.dependencies import get_strategy_service
from margin.api.main import create_app
from margin.storage.base import Base
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)
from margin.strategy.db_models import StrategyProfileRow, StrategyVersionRow


def test_strategy_api_persists_across_default_service_instances(database_url, monkeypatch):
    """Test that the production strategy dependency persists records in PostgreSQL."""
    monkeypatch.setenv("MARGIN_DATABASE_URL", database_url)
    get_strategy_service.cache_clear()
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    with session_factory.begin() as session:
        session.query(StrategyVersionRow).delete()
        session.query(StrategyProfileRow).delete()

    try:
        first_client = TestClient(create_app())
        response = first_client.post(
            "/strategies",
            headers={"Idempotency-Key": "strategy-postgres-create"},
            json={"owner_id": "user_1", "template": "value_quality"},
        )
        assert response.status_code == 200
        strategy_id = response.json()["strategy_id"]

        get_strategy_service.cache_clear()
        second_client = TestClient(create_app())
        listed = second_client.get("/strategies", params={"owner_id": "user_1"})

        assert listed.status_code == 200
        assert [item["strategy_id"] for item in listed.json()] == [strategy_id]
    finally:
        get_strategy_service.cache_clear()
        with session_factory.begin() as session:
            session.query(StrategyVersionRow).delete()
            session.query(StrategyProfileRow).delete()
        engine.dispose()
