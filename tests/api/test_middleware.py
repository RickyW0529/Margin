"""Tests for trace-id and logging middleware."""

from __future__ import annotations

from fastapi import Request
from fastapi.testclient import TestClient

from margin.api.main import create_app
from margin.api.middleware import _get_trace_id


def test_trace_id_header_propagates():
    app = create_app()

    @app.get("/echo-trace")
    def echo_trace(request: Request):
        return {"trace_id": _get_trace_id(request)}

    client = TestClient(app)
    response = client.get("/echo-trace", headers={"x-margin-trace-id": "t-123"})
    assert response.json()["trace_id"] == "t-123"
