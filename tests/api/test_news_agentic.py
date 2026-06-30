"""API tests for agentic news acquisition."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from margin.api import dependencies as dependency_module
from margin.api.dependencies import get_agentic_news_service
from margin.api.main import create_app
from margin.news.agentic_models import NewsAgentRun, NewsAgentRunStatus
from margin.settings import get_settings


def test_agentic_news_refresh_starts_from_quant_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that the agentic news endpoint starts a PASS-only quant-run refresh."""
    monkeypatch.setenv("MARGIN_ADMIN_API_TOKEN", "admin-test-token")
    monkeypatch.setenv("MARGIN_CSRF_TOKEN", "valid")
    get_settings.cache_clear()
    fake_service = FakeAgenticNewsService()
    app = create_app()
    app.dependency_overrides[get_agentic_news_service] = lambda: fake_service

    response = TestClient(app).post(
        "/api/v1/news/agentic-refresh",
        json={
            "scope_version_id": "scope_v1",
            "quant_run_id": "qr_test",
            "decision_at": "2026-06-29T00:00:00Z",
            "include_near_threshold": False,
            "max_workers": 2,
        },
        headers={
            "Authorization": "Bearer admin-test-token",
            "X-CSRF-Token": "valid",
            "Idempotency-Key": "agentic-news-test",
        },
    )

    assert response.status_code == 202
    assert response.json() == {
        "run_id": "nar_api",
        "status": "completed",
        "target_count": 1,
        "include_near_threshold": False,
    }
    assert fake_service.request == {
        "scope_version_id": "scope_v1",
        "quant_run_id": "qr_test",
        "decision_at": datetime(2026, 6, 29, tzinfo=UTC),
        "include_near_threshold": False,
        "max_workers": 2,
        "idempotency_key": "agentic-news-test",
    }


def test_agentic_provider_builder_falls_back_to_env_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that agentic news falls back to env providers without runtime secrets."""

    class MissingRuntimeFactory:
        def build_llm(self) -> Any:
            """Raise an error simulating missing runtime secret configuration."""
            raise RuntimeError("MARGIN_SECRET_MASTER_KEY is not configured")

    monkeypatch.setattr(
        dependency_module,
        "get_provider_runtime_factory",
        lambda: MissingRuntimeFactory(),
    )
    monkeypatch.setattr(
        dependency_module,
        "build_llm_provider",
        lambda settings: "env-llm",
    )
    monkeypatch.setattr(
        dependency_module,
        "build_websearch_provider",
        lambda settings: "env-websearch",
    )

    llm_provider, websearch_provider = dependency_module._build_agentic_news_providers(
        SimpleNamespace()
    )

    assert llm_provider == "env-llm"
    assert websearch_provider == "env-websearch"


def test_agentic_llm_service_uses_non_graph_audit() -> None:
    """Test that agentic news LLM calls are not forced through LangGraph audit FKs."""
    service = dependency_module._build_agentic_news_llm_service("provider")

    assert service._audit.__class__.__name__ == "MemoryLLMCallAuditRepository"


class FakeAgenticNewsService:
    """Fake agentic news service used by the API test."""

    def __init__(self) -> None:
        self.request: dict[str, object] = {}

    def run_for_quant_run(
        self,
        *,
        scope_version_id: str,
        quant_run_id: str,
        decision_at: datetime,
        include_near_threshold: bool = False,
        max_workers: int = 4,
        idempotency_key: str | None = None,
    ) -> NewsAgentRun:
        """Capture the request and return a completed run.

        Args:
            scope_version_id: The research scope version identifier.
            quant_run_id: The quant run to refresh news for.
            decision_at: The decision timestamp for the refresh.
            include_near_threshold: Whether to include near-threshold candidates.
            max_workers: Maximum number of parallel workers.

        Returns:
            A completed ``NewsAgentRun`` instance.
        """
        self.request = {
            "scope_version_id": scope_version_id,
            "quant_run_id": quant_run_id,
            "decision_at": decision_at,
            "include_near_threshold": include_near_threshold,
            "max_workers": max_workers,
            "idempotency_key": idempotency_key,
        }
        return NewsAgentRun(
            run_id="nar_api",
            scope_version_id=scope_version_id,
            quant_run_id=quant_run_id,
            decision_at=decision_at,
            status=NewsAgentRunStatus.COMPLETED,
            target_count=1,
            include_near_threshold=include_near_threshold,
            config_hash="sha256:api",
        )
