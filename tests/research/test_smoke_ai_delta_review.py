"""Command-contract tests for the module 06 AI delta-review smoke script.

This module verifies that the smoke script outputs token-safe contract lines
for each review mode, that the real-LLM smoke fails closed when LLM config
is incomplete without leaking secrets, and that the real-LLM decision prompt
contains the deterministic decision contract.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from scripts import smoke_ai_delta_review


def test_ai_delta_review_smoke_outputs_token_safe_contract_lines() -> None:
    """Verify the smoke script outputs one token-safe contract line per mode.

    Returns:
        None: .
    """
    for mode in ("carry", "delta", "full"):
        result = subprocess.run(
            [sys.executable, "scripts/smoke_ai_delta_review.py", "--mode", mode],
            cwd=Path(__file__).resolve().parents[2],
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )

        assert result.returncode == 0
        fields = dict(item.split("=", 1) for item in result.stdout.strip().split())
        assert set(fields) == {
            "mode",
            "status",
            "graph_run_id",
            "outcome",
            "llm_calls",
            "tool_calls",
            "evidence_packages",
        }
        assert fields["mode"] == mode
        assert fields["status"] == "ok"
        assert fields["graph_run_id"].startswith("graph_")
        if mode == "carry":
            assert fields["llm_calls"] == "0"
            assert fields["evidence_packages"] == "0"
        else:
            assert int(fields["llm_calls"]) > 0
            assert int(fields["evidence_packages"]) > 0
        assert result.stderr == ""
        assert "api_key" not in result.stdout.lower()
        assert "prompt" not in result.stdout.lower()


def test_ai_delta_review_real_llm_smoke_blocks_without_llm_config() -> None:
    """Verify the required real-LLM smoke fails closed when LLM config is incomplete.

    Returns:
        None: .
    """
    result = subprocess.run(
        [
            sys.executable,
            "scripts/smoke_ai_delta_review.py",
            "--mode",
            "delta",
            "--require-real-llm",
        ],
        cwd=Path(__file__).resolve().parents[2],
        env={
            "MARGIN_LLM_API_KEY": "should-not-leak",
            "MARGIN_LLM_BASE_URL": "",
            "MARGIN_LLM_MODEL": "real-model",
        },
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 2
    assert "external_blocker=missing_llm_config" in result.stdout
    assert "should-not-leak" not in result.stdout + result.stderr


def test_real_llm_smoke_prompt_contains_deterministic_decision_contract() -> None:
    """Verify the real-LLM smoke prompt contains the deterministic decision contract.

    Returns:
        None: .
    """
    state = SimpleNamespace(
        security_id="000001.SZ",
        decision_at=datetime(2026, 6, 23, tzinfo=UTC),
        review_mode="delta_review",
        change_set={"material_news_change": True},
    )

    prompt = smoke_ai_delta_review._build_real_llm_decision_prompt(
        state,
        ["ev-smoke-delta"],
    )

    assert "material_news_change=True" in prompt
    assert "outcome must be update_assessment" in prompt
    assert "ev-smoke-delta" in prompt
