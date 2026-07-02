"""Tests for the local development supervisor script."""

from __future__ import annotations

from pathlib import Path

from scripts import dev


def test_dev_commands_bind_to_loopback_without_duplicate_next_flags() -> None:
    """Local dev commands should avoid wildcard binds and duplicate Next flags."""
    config = dev.DevConfig(
        root=Path("/repo"),
        host="127.0.0.1",
        api_port=8000,
        web_port=3000,
    )

    assert dev.build_api_command(config, python="/repo/.venv/bin/python") == [
        "/repo/.venv/bin/python",
        "-m",
        "uvicorn",
        "margin.api.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
    ]
    assert dev.build_web_command(config) == [
        "npx",
        "next",
        "dev",
        "--hostname",
        "127.0.0.1",
        "--port",
        "3000",
    ]


def test_dev_environment_forces_localhost_proxy_bypass() -> None:
    """The dev supervisor should keep localhost traffic out of proxies/VPN."""
    env = dev.with_local_no_proxy({"NO_PROXY": "example.com"})

    assert env["NO_PROXY"] == "example.com,localhost,127.0.0.1,::1"
    assert env["no_proxy"] == "example.com,localhost,127.0.0.1,::1"


def test_project_worker_selection_ignores_other_repositories() -> None:
    """Clean mode may only target margin.worker processes from this checkout."""
    root = Path("/repo")
    rows = [
        dev.ProcessRow(101, "python -m margin.worker"),
        dev.ProcessRow(202, "python -m margin.worker"),
        dev.ProcessRow(303, "python -m other.worker"),
    ]
    cwd_by_pid = {
        101: Path("/repo"),
        202: Path("/other"),
        303: Path("/repo"),
    }

    selected = dev.project_worker_pids(
        rows,
        root=root,
        cwd_lookup=lambda pid: cwd_by_pid.get(pid),
    )

    assert selected == [101]
