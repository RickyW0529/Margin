"""Command-contract tests for the module 04 text-indexing smoke script.

Verifies that the smoke script fails closed when embedding configuration is missing
(without leaking secret values) and that it falls back to settings/.env-backed
configuration when environment variables are unset.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import scripts.smoke_text_indexing as smoke


def test_text_indexing_smoke_blocks_without_embedding_config_and_masks_secret(
    database_url: str,
) -> None:
    """Missing embedding config must fail closed without printing secret values.

    Runs the smoke script in a subprocess with an API key set but no base URL,
    model, or dimension, then verifies that the exit code indicates a blocked
    provider and that the secret key value never appears in stdout or stderr.

    Args:
        database_url: pytest fixture providing the connection URL for the test database.
    """
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
    """The real smoke path should also work with settings/.env-backed config.

    Removes all embedding-related environment variables and patches ``MarginSettings``
    with a dummy, then verifies that ``_embedding_config`` reads values from the
    settings object instead of the environment.

    Args:
        monkeypatch: pytest fixture for patching environment variables and attributes.
    """

    class DummySecret:
        """Stub secret value object mimicking pydantic ``SecretStr``."""

        def get_secret_value(self) -> str:
            """Return the hardcoded secret string used by the dummy settings."""
            return "settings-secret"

    class DummySettings:
        """Stub settings object providing embedding configuration values.

        Attributes:
            embedding_api_key: dummy secret wrapping the API key.
            embedding_base_url: fake embedding service base URL.
            embedding_model: fake embedding model name.
            embedding_dimension: fake embedding vector dimension.
        """
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
