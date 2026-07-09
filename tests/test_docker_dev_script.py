"""Tests for the Docker Compose development launcher."""

from __future__ import annotations

from pathlib import Path
from typing import TextIO

from scripts import docker_dev


def test_choose_ports_skips_busy_defaults(monkeypatch) -> None:
    """Docker startup should pick free localhost ports when defaults are busy.

    Args:
        monkeypatch: Any: .

    Returns:
        None: .
    """
    busy = {5432, 8000, 3000, 9090, 3002}

    monkeypatch.setattr(docker_dev, "current_compose_ports", lambda *_args, **_kwargs: {})

    ports = docker_dev.choose_ports(
        root=Path("/repo"),
        dotenv_values={
            "MARGIN_POSTGRES_PORT": "5432",
            "MARGIN_API_PORT": "8000",
            "MARGIN_WEB_PORT": "3000",
            "MARGIN_PROMETHEUS_PORT": "9090",
            "GRAFANA_PORT": "3002",
        },
        state_values={},
        base_env={},
        is_port_available=lambda port: port not in busy,
    )

    assert ports == {
        "GRAFANA_PORT": "3003",
        "MARGIN_API_PORT": "8001",
        "MARGIN_POSTGRES_PORT": "5433",
        "MARGIN_PROMETHEUS_PORT": "9091",
        "MARGIN_WEB_PORT": "3001",
    }


def test_parse_published_port_supports_compose_output() -> None:
    """Existing Compose mappings should be reusable across repeated starts.

    Returns:
        None: .
    """
    assert docker_dev.parse_published_port("127.0.0.1:8000") == 8000
    assert docker_dev.parse_published_port("0.0.0.0:3000") == 3000
    assert docker_dev.parse_published_port("") is None


def test_run_compose_up_uses_detached_mode_for_managed_progress() -> None:
    """The helper should not attach to noisy Compose logs during normal startup.

    Returns:
        None: .
    """
    captured: dict[str, object] = {}

    class FakeProcess:
        """Class implementing FakeProcess.."""

        stdout: TextIO | None = None
        returncode = 0

        def poll(self) -> int:
            """Process poll.

            Returns:
                int: .
            """
            return 0

    def fake_popen(command, **kwargs):  # noqa: ANN001
        """Process fake_popen.

        Args:
            command: Any: .
            **kwargs: Any: .

        Returns:
            Any: .
        """
        captured["command"] = command
        captured["kwargs"] = kwargs
        return FakeProcess()

    exit_code = docker_dev.run_compose_up(
        root=Path("/repo"),
        env={},
        build=True,
        popen=fake_popen,
    )

    assert exit_code == 0
    assert captured["command"] == ["docker", "compose", "up", "-d", "--build"]


def test_progress_line_reports_pending_health_status() -> None:
    """Startup progress should show completed milestones and pending services.

    Returns:
        None: .
    """
    statuses = docker_dev.parse_compose_ps_json(
        "\n".join(
            [
                '{"Service":"postgres","State":"running","Health":"healthy","ExitCode":0,'
                '"Status":"Up (healthy)"}',
                '{"Service":"migrate","State":"exited","Health":"","ExitCode":0,'
                '"Status":"Exited (0)"}',
                '{"Service":"bootstrap","State":"exited","Health":"","ExitCode":0,'
                '"Status":"Exited (0)"}',
                '{"Service":"api","State":"running","Health":"starting","ExitCode":0,'
                '"Status":"Up (health: starting)"}',
            ]
        )
    )

    line = docker_dev.format_progress_line(statuses, elapsed_seconds=12)

    assert "[##########--------------] 4/9" in line
    assert "elapsed=12s" in line
    assert "API=starting" in line
    assert "Worker=pending" in line


def test_startup_complete_requires_one_shot_exit_zero_and_healthy_services() -> None:
    """Readiness should distinguish completed one-shot jobs and healthchecks.

    Returns:
        None: .
    """
    statuses = {
        "postgres": docker_dev.ComposeServiceStatus(
            service="postgres",
            state="running",
            health="healthy",
            exit_code=0,
            status="Up (healthy)",
        ),
        "migrate": docker_dev.ComposeServiceStatus(
            service="migrate",
            state="exited",
            health="",
            exit_code=0,
            status="Exited (0)",
        ),
        "bootstrap": docker_dev.ComposeServiceStatus(
            service="bootstrap",
            state="exited",
            health="",
            exit_code=0,
            status="Exited (0)",
        ),
        "api": docker_dev.ComposeServiceStatus(
            service="api",
            state="running",
            health="healthy",
            exit_code=0,
            status="Up (healthy)",
        ),
        "worker": docker_dev.ComposeServiceStatus(
            service="worker",
            state="running",
            health="healthy",
            exit_code=0,
            status="Up (healthy)",
        ),
        "web": docker_dev.ComposeServiceStatus(
            service="web",
            state="running",
            health="",
            exit_code=0,
            status="Up",
        ),
        "prometheus": docker_dev.ComposeServiceStatus(
            service="prometheus",
            state="running",
            health="",
            exit_code=0,
            status="Up",
        ),
        "grafana": docker_dev.ComposeServiceStatus(
            service="grafana",
            state="running",
            health="",
            exit_code=0,
            status="Up",
        ),
    }

    assert docker_dev.startup_complete(statuses) is True
