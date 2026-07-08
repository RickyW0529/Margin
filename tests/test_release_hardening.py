"""Static release-hardening checks for Docker and frontend/backend contracts."""

from __future__ import annotations

from pathlib import Path


def test_backend_dockerfile_installs_from_uv_lock() -> None:
    """Docker image builds must use the committed lockfile, not open-ended pip resolution."""
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert "COPY pyproject.toml uv.lock README.md ./" in dockerfile
    assert "uv sync --frozen" in dockerfile
    assert 'pip install -e ".[data]"' not in dockerfile


def test_compose_does_not_default_grafana_to_margin_password() -> None:
    """Compose must not encode the old public Grafana default password."""
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    env_example = Path(".env.example").read_text(encoding="utf-8")

    assert "GRAFANA_ADMIN_PASSWORD:-margin" not in compose
    assert "GRAFANA_ADMIN_PASSWORD=margin" not in env_example


def test_ci_runs_api_openapi_contract_smoke() -> None:
    """CI must catch API import or critical route contract regressions."""
    ci = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "API import and route smoke" in ci
    assert "API import smoke in backend image" in ci
    assert "docker build -t margin-api-ci ." in ci
    assert "/api/v1/agent-runs/user-qna" in ci
