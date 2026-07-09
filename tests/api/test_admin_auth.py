"""Tests for local-admin mutation guardrails."""

from __future__ import annotations

from fastapi import HTTPException

from margin.api.dependencies import require_local_admin
from margin.settings import MarginSettings


def test_local_admin_allows_development_without_token(monkeypatch) -> None:
    """Development remains local-first and does not require bearer auth.

    Args:
        monkeypatch: Any: .

    Returns:
        None: .
    """
    monkeypatch.setattr(
        "margin.api.dependencies.get_settings",
        lambda: MarginSettings(_env_file=None, environment="development"),
    )

    assert require_local_admin() == "local-admin"


def test_local_admin_requires_bearer_token_in_production(monkeypatch) -> None:
    """Production mutations require a configured bearer token.

    Args:
        monkeypatch: Any: .

    Returns:
        None: .
    """
    monkeypatch.setattr(
        "margin.api.dependencies.get_settings",
        lambda: MarginSettings(
            _env_file=None,
            environment="production",
            database_url="postgresql+psycopg://margin_app:strong@db:5432/margin",
            secret_master_key="!" * 32,
            admin_api_token="admin-secret",
        ),
    )

    try:
        require_local_admin()
    except HTTPException as exc:
        assert exc.status_code == 401
    else:  # pragma: no cover - explicit failure path
        raise AssertionError("production auth without token should fail")

    assert require_local_admin("Bearer admin-secret") == "local-admin"
