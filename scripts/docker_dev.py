#!/usr/bin/env python3
"""Docker Compose launcher with automatic local host port selection."""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DockerPort:
    """One host-port mapping controlled by a Compose environment variable."""

    env_key: str
    service: str
    container_port: int
    default_port: int
    label: str


DOCKER_PORTS: tuple[DockerPort, ...] = (
    DockerPort("MARGIN_POSTGRES_PORT", "postgres", 5432, 5432, "Postgres"),
    DockerPort("MARGIN_API_PORT", "api", 8000, 8000, "API"),
    DockerPort("MARGIN_WEB_PORT", "web", 3000, 3000, "Web"),
    DockerPort("MARGIN_PROMETHEUS_PORT", "prometheus", 9090, 9090, "Prometheus"),
    DockerPort("GRAFANA_PORT", "grafana", 3000, 3002, "Grafana"),
)

STATE_FILE = Path(".margin/docker/ports.env")


def main(argv: list[str] | None = None) -> int:
    """Run the Docker development helper."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        nargs="?",
        choices=("up", "restart", "down", "status"),
        default="up",
    )
    parser.add_argument(
        "-d",
        "--detach",
        action="store_true",
        help="Run docker compose in detached mode",
    )
    parser.add_argument(
        "--no-build",
        action="store_true",
        help="Skip docker compose build during up",
    )
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    if args.command == "down":
        return subprocess.call(["docker", "compose", "down"], cwd=root)
    if args.command == "status":
        return subprocess.call(["docker", "compose", "ps"], cwd=root)
    if args.command == "restart":
        down_exit = subprocess.call(["docker", "compose", "down"], cwd=root)
        if down_exit:
            return down_exit

    ports = choose_ports(
        root=root,
        dotenv_values=read_env_file(root / ".env"),
        state_values=read_env_file(root / STATE_FILE),
        base_env=os.environ,
    )
    write_env_file(root / STATE_FILE, ports)
    print_port_summary(ports)

    command = ["docker", "compose", "up"]
    if not args.no_build:
        command.append("--build")
    if args.detach:
        command.append("-d")
    return subprocess.call(command, cwd=root, env={**os.environ, **ports})


def choose_ports(
    *,
    root: Path,
    dotenv_values: Mapping[str, str],
    state_values: Mapping[str, str],
    base_env: Mapping[str, str],
    is_port_available: Callable[[int], bool] | None = None,
) -> dict[str, str]:
    """Choose concrete host ports for Docker Compose services."""
    is_port_available = is_port_available or is_loopback_port_available
    existing_ports = current_compose_ports(root, base_env)
    selected: dict[str, str] = {}
    reserved: set[int] = set()

    for mapping in DOCKER_PORTS:
        existing = existing_ports.get(mapping.env_key)
        if existing is not None:
            selected[mapping.env_key] = str(existing)
            reserved.add(existing)
            continue

        preferred = preferred_port(mapping, base_env, state_values, dotenv_values)
        port = first_available_port(
            preferred,
            reserved=reserved,
            is_port_available=is_port_available,
        )
        selected[mapping.env_key] = str(port)
        reserved.add(port)

    return selected


def preferred_port(
    mapping: DockerPort,
    base_env: Mapping[str, str],
    state_values: Mapping[str, str],
    dotenv_values: Mapping[str, str],
) -> int:
    """Return the preferred starting port for one mapping."""
    for source in (base_env, state_values, dotenv_values):
        raw_value = source.get(mapping.env_key)
        if raw_value:
            try:
                return int(raw_value)
            except ValueError:
                continue
    return mapping.default_port


def first_available_port(
    preferred: int,
    *,
    reserved: set[int],
    is_port_available: Callable[[int], bool],
    search_span: int = 300,
) -> int:
    """Return the preferred port, or the next free loopback port."""
    for port in range(preferred, preferred + search_span + 1):
        if port not in reserved and is_port_available(port):
            return port
    raise RuntimeError(
        f"No free localhost port found from {preferred} to {preferred + search_span}"
    )


def is_loopback_port_available(port: int) -> bool:
    """Return whether a TCP port can be bound on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def current_compose_ports(root: Path, base_env: Mapping[str, str]) -> dict[str, int]:
    """Return currently published Compose ports so repeated runs stay stable."""
    ports: dict[str, int] = {}
    for mapping in DOCKER_PORTS:
        result = subprocess.run(
            ["docker", "compose", "port", mapping.service, str(mapping.container_port)],
            cwd=root,
            env=dict(base_env),
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            continue
        port = parse_published_port(result.stdout.strip())
        if port is not None:
            ports[mapping.env_key] = port
    return ports


def parse_published_port(value: str) -> int | None:
    """Parse ``docker compose port`` output such as ``127.0.0.1:8000``."""
    if not value:
        return None
    _, separator, port_text = value.rpartition(":")
    if not separator:
        return None
    try:
        return int(port_text)
    except ValueError:
        return None


def read_env_file(path: Path) -> dict[str, str]:
    """Read a simple KEY=VALUE env file without expanding shell syntax."""
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return values

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", maxsplit=1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def write_env_file(path: Path, values: Mapping[str, str]) -> None:
    """Persist selected ports for stable subsequent Docker runs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(f"{key}={values[key]}" for key in sorted(values)) + "\n"
    path.write_text(content, encoding="utf-8")


def print_port_summary(ports: Mapping[str, str]) -> None:
    """Print the selected local URLs before Compose starts."""
    print("Selected Docker ports:")
    for mapping in DOCKER_PORTS:
        print(f"  {mapping.label}: 127.0.0.1:{ports[mapping.env_key]}")
    print(f"Open: http://localhost:{ports['MARGIN_WEB_PORT']}")


if __name__ == "__main__":
    sys.exit(main())
