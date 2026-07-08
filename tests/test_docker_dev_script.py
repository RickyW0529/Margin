"""Tests for the Docker Compose development launcher."""

from __future__ import annotations

from pathlib import Path

from scripts import docker_dev


def test_choose_ports_skips_busy_defaults(monkeypatch) -> None:
    """Docker startup should pick free localhost ports when defaults are busy."""
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
    """Existing Compose mappings should be reusable across repeated starts."""
    assert docker_dev.parse_published_port("127.0.0.1:8000") == 8000
    assert docker_dev.parse_published_port("0.0.0.0:3000") == 3000
    assert docker_dev.parse_published_port("") is None
