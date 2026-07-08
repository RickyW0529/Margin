#!/usr/bin/env python3
"""Docker Compose launcher with automatic local host port selection."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from threading import Thread
from typing import Protocol, TextIO


class ComposeProcess(Protocol):
    """Small protocol for the managed ``docker compose up`` process."""

    stdout: TextIO | None
    returncode: int | None

    def poll(self) -> int | None:
        """Return the subprocess exit status, or ``None`` while running."""
        ...


@dataclass(frozen=True)
class DockerPort:
    """One host-port mapping controlled by a Compose environment variable."""

    env_key: str
    service: str
    container_port: int
    default_port: int
    label: str


@dataclass(frozen=True)
class StartupService:
    """One service milestone displayed in the startup progress bar."""

    service: str
    label: str
    ready_when: str


@dataclass(frozen=True)
class ComposeServiceStatus:
    """Compact service status parsed from ``docker compose ps``."""

    service: str
    state: str
    health: str
    exit_code: int
    status: str


DOCKER_PORTS: tuple[DockerPort, ...] = (
    DockerPort("MARGIN_POSTGRES_PORT", "postgres", 5432, 5432, "Postgres"),
    DockerPort("MARGIN_API_PORT", "api", 8000, 8000, "API"),
    DockerPort("MARGIN_WEB_PORT", "web", 3000, 3000, "Web"),
    DockerPort("MARGIN_PROMETHEUS_PORT", "prometheus", 9090, 9090, "Prometheus"),
    DockerPort("GRAFANA_PORT", "grafana", 3000, 3002, "Grafana"),
)

STARTUP_SERVICES: tuple[StartupService, ...] = (
    StartupService("postgres", "Postgres", "healthy"),
    StartupService("migrate", "Migrations", "exited_0"),
    StartupService("bootstrap", "Bootstrap", "exited_0"),
    StartupService("api", "API", "healthy"),
    StartupService("worker", "Worker", "healthy"),
    StartupService("web", "Web", "running"),
    StartupService("prometheus", "Prometheus", "running"),
    StartupService("grafana", "Grafana", "running"),
)

STATE_FILE = Path(".margin/docker/ports.env")
DEFAULT_STARTUP_TIMEOUT_SECONDS = 300


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
        help="Compatibility flag; startup is already managed in detached mode",
    )
    parser.add_argument(
        "--no-build",
        action="store_true",
        help="Skip docker compose build during up",
    )
    parser.add_argument(
        "--startup-timeout",
        default=DEFAULT_STARTUP_TIMEOUT_SECONDS,
        type=int,
        help="Seconds to wait for Docker services to become ready",
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

    print("Starting Docker services. First builds can take several minutes.")
    compose_exit = run_compose_up(
        root=root,
        env={**os.environ, **ports},
        build=not args.no_build,
    )
    if compose_exit:
        return compose_exit

    return wait_for_startup(
        root=root,
        env={**os.environ, **ports},
        ports=ports,
        timeout_seconds=args.startup_timeout,
    )


def run_compose_up(
    *,
    root: Path,
    env: Mapping[str, str],
    build: bool,
    popen: Callable[..., ComposeProcess] = subprocess.Popen,
) -> int:
    """Start Docker Compose in detached mode so the helper can report progress."""
    command = ["docker", "compose", "up", "-d"]
    if build:
        command.append("--build")

    output_lines: deque[str] = deque(maxlen=80)
    process = popen(
        command,
        cwd=root,
        env=dict(env),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    if process.stdout is not None:
        Thread(
            target=collect_process_output,
            args=(process.stdout, output_lines),
            daemon=True,
        ).start()

    started_at = time.monotonic()
    last_line_length = 0
    while process.poll() is None:
        line = (
            f"{render_progress_bar(1, len(STARTUP_SERVICES) + 1)} "
            f"1/{len(STARTUP_SERVICES) + 1} elapsed={int(time.monotonic() - started_at)}s "
            "waiting: Docker build/start"
        )
        print("\r" + line + " " * max(0, last_line_length - len(line)), end="", flush=True)
        last_line_length = len(line)
        time.sleep(1)

    print()
    if process.returncode:
        print(f"docker compose up failed exit={process.returncode}")
        for line in output_lines:
            print(line)
        return int(process.returncode)
    return 0


def collect_process_output(stream: TextIO, output_lines: deque[str]) -> None:
    """Drain subprocess output so long builds cannot block on a full pipe."""
    for line in stream:
        output_lines.append(line.rstrip())


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


def wait_for_startup(
    *,
    root: Path,
    env: Mapping[str, str],
    ports: Mapping[str, str],
    timeout_seconds: int,
    poll_interval_seconds: float = 1.0,
) -> int:
    """Poll Docker Compose service state and render startup progress."""
    started_at = time.monotonic()
    deadline = time.monotonic() + timeout_seconds
    last_line_length = 0

    while True:
        statuses = compose_service_statuses(root, env)
        failed = failed_startup_services(statuses)
        line = format_progress_line(statuses, int(time.monotonic() - started_at))
        print("\r" + line + " " * max(0, last_line_length - len(line)), end="", flush=True)
        last_line_length = len(line)

        if failed:
            print()
            for service in failed:
                status = statuses[service.service]
                print(f"{service.label} failed: {status.status}")
            print("Inspect logs with: docker compose logs --tail=80")
            return 1

        if startup_complete(statuses):
            print()
            print("Startup complete.")
            print_port_summary(ports)
            print("Logs: docker compose logs -f")
            return 0

        if time.monotonic() >= deadline:
            print()
            print("Startup timed out before all services became ready.")
            print("Inspect status with: docker compose ps")
            print("Inspect logs with: docker compose logs --tail=120")
            return 1

        time.sleep(poll_interval_seconds)


def compose_service_statuses(root: Path, env: Mapping[str, str]) -> dict[str, ComposeServiceStatus]:
    """Read current Docker Compose service statuses."""
    result = subprocess.run(
        ["docker", "compose", "ps", "-a", "--format", "json"],
        cwd=root,
        env=dict(env),
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        return {}
    return parse_compose_ps_json(result.stdout)


def parse_compose_ps_json(output: str) -> dict[str, ComposeServiceStatus]:
    """Parse JSON-lines output from ``docker compose ps --format json``."""
    statuses: dict[str, ComposeServiceStatus] = {}
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        service = str(payload.get("Service") or "")
        if not service:
            continue
        statuses[service] = ComposeServiceStatus(
            service=service,
            state=str(payload.get("State") or ""),
            health=str(payload.get("Health") or ""),
            exit_code=int(payload.get("ExitCode") or 0),
            status=str(payload.get("Status") or ""),
        )
    return statuses


def startup_complete(statuses: Mapping[str, ComposeServiceStatus]) -> bool:
    """Return whether every startup milestone is ready."""
    return all(
        service_ready(service, statuses.get(service.service))
        for service in STARTUP_SERVICES
    )


def failed_startup_services(
    statuses: Mapping[str, ComposeServiceStatus],
) -> tuple[StartupService, ...]:
    """Return failed service milestones."""
    failed: list[StartupService] = []
    for service in STARTUP_SERVICES:
        status = statuses.get(service.service)
        if status is None:
            continue
        if status.health == "unhealthy":
            failed.append(service)
        elif status.state == "exited" and service.ready_when != "exited_0":
            failed.append(service)
        elif (
            service.ready_when == "exited_0"
            and status.state == "exited"
            and status.exit_code != 0
        ):
            failed.append(service)
    return tuple(failed)


def service_ready(service: StartupService, status: ComposeServiceStatus | None) -> bool:
    """Return whether one service satisfies its readiness condition."""
    if status is None:
        return False
    if service.ready_when == "healthy":
        return status.health == "healthy"
    if service.ready_when == "exited_0":
        return status.state == "exited" and status.exit_code == 0
    if service.ready_when == "running":
        return status.state == "running" and status.health in ("", "healthy")
    raise ValueError(f"Unknown readiness condition: {service.ready_when}")


def format_progress_line(
    statuses: Mapping[str, ComposeServiceStatus],
    elapsed_seconds: int,
) -> str:
    """Render one startup progress line."""
    completed_services = sum(
        1
        for service in STARTUP_SERVICES
        if service_ready(service, statuses.get(service.service))
    )
    completed = 1 + completed_services
    total = 1 + len(STARTUP_SERVICES)
    waiting = waiting_labels(statuses)
    return (
        f"{render_progress_bar(completed, total)} {completed}/{total} "
        f"elapsed={max(0, elapsed_seconds)}s waiting: {waiting}"
    )


def render_progress_bar(completed: int, total: int, *, width: int = 24) -> str:
    """Render a fixed-width ASCII progress bar."""
    filled = int(width * completed / total) if total else width
    return "[" + "#" * filled + "-" * (width - filled) + "]"


def waiting_labels(statuses: Mapping[str, ComposeServiceStatus]) -> str:
    """Return a compact human-readable list of pending milestones."""
    labels: list[str] = []
    for service in STARTUP_SERVICES:
        status = statuses.get(service.service)
        if service_ready(service, status):
            continue
        if status is None:
            labels.append(f"{service.label}=pending")
        elif status.health:
            labels.append(f"{service.label}={status.health}")
        else:
            labels.append(f"{service.label}={status.state or 'pending'}")
        if len(labels) == 3:
            break
    return ", ".join(labels) if labels else "ready"


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
    print("Selected Docker ports:", flush=True)
    for mapping in DOCKER_PORTS:
        print(f"  {mapping.label}: 127.0.0.1:{ports[mapping.env_key]}", flush=True)
    print(f"Open: http://localhost:{ports['MARGIN_WEB_PORT']}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
