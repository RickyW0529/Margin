"""Command-contract tests for the module 05 RAG evidence smoke script."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from sqlalchemy.engine import make_url

from scripts.verify_migrations import verify_clean_database


def test_rag_evidence_smoke_is_idempotent_and_outputs_only_contract_fields(
    database_url: str,
) -> None:
    """rag evidence smoke is idempotent and outputs only contract fields."""
    url = make_url(database_url)
    database_name = f"{url.database}_rag_smoke"
    verify_clean_database(
        database_url,
        database_name=database_name,
        drop_existing=True,
        keep_database=True,
    )
    smoke_database_url = url.set(database=database_name).render_as_string(
        hide_password=False
    )
    command = [
        sys.executable,
        "scripts/smoke_rag_evidence.py",
        "--database-url",
        smoke_database_url,
        "--security-id",
        "SMOKE05.SZ",
        "--decision-at",
        "2026-06-22T00:00:00Z",
        "--create-sample",
    ]

    try:
        first = _run(command)
        second = _run(command)
    finally:
        verify_clean_database(
            database_url,
            database_name=database_name,
            drop_existing=True,
        )

    assert first.returncode == 0
    assert second.returncode == 0
    for result in (first, second):
        fields = dict(item.split("=", 1) for item in result.stdout.strip().split())
        assert set(fields) == {
            "status",
            "package_id",
            "evidence_count",
            "claim_status",
            "validation_status",
        }
        assert fields["status"] == "ok"
        assert fields["evidence_count"] == "1"
        assert fields["claim_status"] == "supported"
        assert fields["validation_status"] == "pass"
        assert result.stderr == ""


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    """run."""
    return subprocess.run(
        command,
        cwd=Path(__file__).resolve().parents[2],
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
