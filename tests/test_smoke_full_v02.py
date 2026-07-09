"""Full v0.2 smoke harness command-contract tests.

Verifies that the full smoke script suppresses noisy stage output, requires real
provider credentials without leaking secrets, accepts secret-manager env aliases,
and can skip unconfigured providers in dry-run mode.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.engine import make_url

import scripts.smoke_full_v02 as smoke
from margin.core.provider import HealthCheckResult, ProviderStatus
from scripts.smoke_full_v02 import _stage
from scripts.verify_migrations import verify_clean_database


def test_smoke_stage_suppresses_noisy_stage_output(capsys) -> None:
    """Test that the smoke stage helper suppresses noisy stdout/stderr from stages.

    Args:
        capsys: Any: .

    Returns:
        None: .
    """

    def noisy_stage() -> dict[str, str]:
        """Noisy stage that prints to stdout and stderr but returns an empty dict.

        Returns:
            dict[str, str]: .
        """
        print("provider raw output should not be printed")
        print("provider stderr should not be printed", file=sys.stderr)
        return {}

    result = _stage("noisy", noisy_stage)

    captured = capsys.readouterr()
    assert result.status == "passed"
    assert captured.out == ""
    assert captured.err == ""


def test_full_smoke_requires_real_provider_credentials_without_leaking_secret(
    tmp_path: Path,
    database_url: str,
) -> None:
    """Test that the full smoke requires real provider credentials without leaking secrets.

    Args:
        tmp_path: Path: .
        database_url: str: .

    Returns:
        None: .
    """
    output_path = tmp_path / "smoke.json"
    env = {
        "MARGIN_DATABASE_URL": database_url,
        "MARGIN_TUSHARE_TOKEN": "",
        "MARGIN_WEBSEARCH_API_KEY": "",
        "MARGIN_LLM_API_KEY": "should-not-leak",
        "MARGIN_LLM_BASE_URL": "",
        "MARGIN_EMBEDDING_API_KEY": "",
        "MARGIN_EMBEDDING_BASE_URL": "",
        "MARGIN_RERANK_API_KEY": "",
        "MARGIN_RERANK_BASE_URL": "",
        "MARGIN_RERANK_MODEL": "",
    }

    result = subprocess.run(
        [
            sys.executable,
            "scripts/smoke_full_v02.py",
            "--skip-compose",
            "--require-real-providers",
            "--providers",
            "tushare,tavily,llm,embedding,rerank",
            "--database-url",
            database_url,
            "--output-json",
            str(output_path),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, **env},
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )

    assert result.returncode == 1
    combined_output = result.stdout + result.stderr + output_path.read_text()
    assert "should-not-leak" not in combined_output
    stdout_payload = json.loads(result.stdout)
    assert all(
        set(stage) <= {"stage", "status", "external_blocker", "error_code"}
        for stage in stdout_payload["stages"]
    )
    assert "detail" not in result.stdout
    payload = json.loads(output_path.read_text())
    provider_stages = {
        stage["stage"]: stage
        for stage in payload["stages"]
        if stage["stage"].startswith("provider:")
    }
    assert provider_stages["provider:tushare"]["external_blocker"] == "missing_secret"
    assert provider_stages["provider:tavily"]["external_blocker"] == "missing_secret"
    assert provider_stages["provider:llm"]["external_blocker"] == "missing_secret"


def test_tushare_smoke_accepts_secret_manager_env_alias(monkeypatch) -> None:
    """Test that the Tushare smoke stage accepts the secret-manager env alias.

    Args:
        monkeypatch: Any: .

    Returns:
        None: .
    """
    calls: dict[str, str | None] = {}

    class DummyTushareProvider:
        """Dummy Tushare provider that records constructor args and returns a healthy check.."""

        def __init__(self, *, token: str, http_url: str | None = None) -> None:
            """Initialize the dummy provider and record the token and URL.

            Args:
                token: str: .
                http_url: str | None: .

            Returns:
                None: .
            """
            calls["token"] = token
            calls["http_url"] = http_url

        def healthcheck(self) -> HealthCheckResult:
            """Return a deterministic healthy check result.

            Returns:
                HealthCheckResult: .
            """
            return HealthCheckResult(
                provider_name="tushare",
                status=ProviderStatus.HEALTHY,
                checked_at=datetime(2026, 6, 22, tzinfo=UTC),
            )

    monkeypatch.delenv("MARGIN_TUSHARE_TOKEN", raising=False)
    monkeypatch.setenv("MARGIN_SECRET_TUSHARE_TOKEN", "secret-manager-token")
    monkeypatch.setattr(smoke, "TushareProvider", DummyTushareProvider)

    result = smoke._run_provider("tushare")

    assert calls["token"] == "secret-manager-token"
    assert result["status"] == "healthy"


def test_full_smoke_dry_run_can_skip_unconfigured_real_providers(
    tmp_path: Path,
    database_url: str,
) -> None:
    """Test that the full smoke dry run can skip unconfigured real providers.

    Args:
        tmp_path: Path: .
        database_url: str: .

    Returns:
        None: .
    """
    output_path = tmp_path / "smoke.json"
    url = make_url(database_url)
    smoke_database_name = f"{url.database}_smoke_full"
    verify_clean_database(
        database_url,
        database_name=smoke_database_name,
        drop_existing=True,
        keep_database=True,
    )
    smoke_database_url = url.set(database=smoke_database_name).render_as_string(hide_password=False)

    try:
        result = subprocess.run(
            [
                sys.executable,
                "scripts/smoke_full_v02.py",
                "--skip-compose",
                "--providers",
                "tushare,tavily",
                "--database-url",
                smoke_database_url,
                "--output-json",
                str(output_path),
            ],
            cwd=Path(__file__).resolve().parents[1],
            text=True,
            capture_output=True,
            check=False,
            timeout=60,
        )
    finally:
        verify_clean_database(
            database_url,
            database_name=smoke_database_name,
            drop_existing=True,
        )

    assert result.returncode == 0
    payload = json.loads(output_path.read_text())
    assert payload["status"] == "ok"
    assert any(stage["status"] == "skipped" for stage in payload["stages"])
