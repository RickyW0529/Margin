"""Smoke script contract tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys


def test_smoke_script_dry_run_masks_configured_tokens(database_url, tmp_path) -> None:
    """Test that the dry-run smoke script output masks configured API tokens."""
    env = {
        **os.environ,
        "PYTHONPATH": "src",
        "MARGIN_DATABASE_URL": database_url,
        "MARGIN_DATA_SNAPSHOT_ROOT": str(tmp_path),
        "MARGIN_SECRET_TUSHARE_TOKEN": "tushare-secret",
    }

    result = subprocess.run(
        [
            sys.executable,
            "scripts/smoke_data_provider.py",
            "--providers",
            "tushare",
            "--end-date",
            "2024-01-05",
            "--dry-run",
        ],
        check=True,
        cwd=os.getcwd(),
        env=env,
        capture_output=True,
        text=True,
    )

    assert "tushare-secret" not in result.stdout
    payload = json.loads(result.stdout)
    assert payload["providers"][0]["provider"] == "tushare"
    assert payload["providers"][0]["status"] == "configured"
