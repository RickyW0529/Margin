"""FastAPI application lifecycle tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from margin.api.main import create_app


def test_create_app_disposes_container_on_shutdown(monkeypatch) -> None:
    """Verify app shutdown disposes process-level runtime resources."""
    disposed = {"value": False}

    class FakeContainer:
        def dispose(self) -> None:
            disposed["value"] = True

    monkeypatch.setattr("margin.api.main.get_app_container", lambda: FakeContainer())

    with TestClient(create_app()) as client:
        assert client.get("/health").status_code == 200

    assert disposed["value"] is True
