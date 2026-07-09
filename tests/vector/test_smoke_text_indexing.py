"""Command-contract tests for the module 04 text-indexing smoke script.

Verifies that the smoke script fails closed when explicit embedding smoke
configuration is missing without leaking secret values.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_text_indexing_smoke_blocks_without_embedding_config_and_masks_secret(
    database_url: str,
) -> None:
    """Missing embedding config must fail closed without printing secret values.

    Args:
        database_url: str: .

    Returns:
        None: .
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
