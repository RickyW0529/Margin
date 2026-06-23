"""Command-contract tests for the module 04 text-indexing smoke script."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import scripts.smoke_text_indexing as smoke


def test_text_indexing_smoke_blocks_without_embedding_config_and_masks_secret(
    database_url: str,
) -> None:
    """Missing embedding config must fail closed without printing secret values."""
    env = {
        **os.environ,
        "MARGIN_DATABASE_URL": database_url,
        "MARGIN_EMBEDDING_API_KEY": "should-not-leak",
        "MARGIN_EMBEDDING_BASE_URL": "",
        "MARGIN_EMBEDDING_MODEL": "",
        "MARGIN_EMBEDDING_DIMENSION": "",
    }

    result = subprocess.run(
        [sys.executable, "scripts/smoke_text_indexing.py"],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 2
    assert "provider=embedding" in result.stdout
    assert "external_blocker=missing_embedding_config" in result.stdout
    assert "should-not-leak" not in result.stdout + result.stderr


def test_text_indexing_smoke_uses_settings_when_embedding_env_is_unset(
    monkeypatch,
) -> None:
    """The real smoke path should also work with settings/.env-backed config."""

    class DummySecret:
        """DummySecret."""
        def get_secret_value(self) -> str:
            """get secret value."""
            return "settings-secret"

    class DummySettings:
        """DummySettings."""
        embedding_api_key = DummySecret()
        embedding_base_url = "https://embedding.example"
        embedding_model = "embedding-model"
        embedding_dimension = 1024

    for key in (
        "MARGIN_EMBEDDING_API_KEY",
        "MARGIN_EMBEDDING_BASE_URL",
        "MARGIN_EMBEDDING_MODEL",
        "MARGIN_EMBEDDING_DIMENSION",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(smoke, "MarginSettings", DummySettings)

    assert smoke._embedding_config() == {
        "api_key": "settings-secret",
        "base_url": "https://embedding.example",
        "model": "embedding-model",
        "dimension": "1024",
    }
