#!/usr/bin/env python3
"""Local development supervisor for Margin.

This script is intentionally process-based instead of HTTP-probe based because
some local agent/sandbox environments cannot complete loopback HTTP handshakes
even when the services are listening. It uses PID files and ``lsof`` to manage
one API, one worker, and one Next.js dev server for this checkout.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

LOCAL_NO_PROXY = ("localhost", "127.0.0.1", "::1")


@dataclass(frozen=True)
class DevConfig:
    """Configuration for local dev processes."""

    root: Path
    host: str = "127.0.0.1"
    api_port: int = 8000
    web_port: int = 3000

    @property
    def web_dir(self) -> Path:
        """Return the Next.js application directory."""
        return self.root / "web"

    @property
    def runtime_dir(self) -> Path:
        """Return the runtime metadata directory."""
        return self.root / ".margin" / "dev"

    @property
    def pid_dir(self) -> Path:
        """Return the PID file directory."""
        return self.runtime_dir / "pids"

    @property
    def log_dir(self) -> Path:
        """Return the log file directory."""
        return self.runtime_dir / "logs"


@dataclass(frozen=True)
class ProcessRow:
    """Small process-list row used by worker cleanup."""

    pid: int
    command: str


def build_api_command(config: DevConfig, *, python: str | None = None) -> list[str]:
    """Build the API command."""
    executable = python or _python_executable(config.root)
    return [
        executable,
        "-m",
        "uvicorn",
        "margin.api.main:app",
        "--host",
        config.host,
        "--port",
        str(config.api_port),
    ]


def build_worker_command(config: DevConfig, *, python: str | None = None) -> list[str]:
    """Build the worker command."""
    executable = python or _python_executable(config.root)
    return [executable, "-m", "margin.worker"]


def build_migrate_command(config: DevConfig, *, python: str | None = None) -> list[str]:
    """Build the local migration command."""
    executable = python or _python_executable(config.root)
    return [executable, "scripts/migrate.py"]


def build_bootstrap_command(config: DevConfig, *, python: str | None = None) -> list[str]:
    """Build the local config bootstrap command."""
    executable = python or _python_executable(config.root)
    return [executable, "scripts/bootstrap_config.py"]


def build_web_command(config: DevConfig) -> list[str]:
    """Build the Next.js dev command without reusing package-script host flags."""
    return [
        "npx",
        "next",
        "dev",
        "--hostname",
        config.host,
        "--port",
        str(config.web_port),
    ]


def with_local_no_proxy(base_env: dict[str, str] | None = None) -> dict[str, str]:
    """Return an environment with localhost forced into proxy bypass lists."""
    env = dict(os.environ if base_env is None else base_env)
    existing = env.get("NO_PROXY") or env.get("no_proxy") or ""
    entries = [item.strip() for item in existing.split(",") if item.strip()]
    for item in LOCAL_NO_PROXY:
        if item not in entries:
            entries.append(item)
    value = ",".join(entries)
    env["NO_PROXY"] = value
    env["no_proxy"] = value
    return env


def project_worker_pids(
    rows: list[ProcessRow],
    *,
    root: Path,
    cwd_lookup: Callable[[int], Path | None],
) -> list[int]:
    """Return margin.worker PIDs whose current working directory is this repo."""
    selected: list[int] = []
    resolved_root = root.resolve()
    for row in rows:
        if "margin.worker" not in row.command:
            continue
        cwd = cwd_lookup(row.pid)
        if cwd is None:
            continue
        try:
            cwd.relative_to(resolved_root)
        except ValueError:
            continue
        selected.append(row.pid)
    return selected


def start(
    config: DevConfig,
    *,
    clean: bool = True,
    skip_postgres: bool = False,
    skip_setup: bool = False,
) -> int:
    """Start local API, worker, and web services."""
    _ensure_runtime_dirs(config)
    if clean:
        stop(config, quiet=True)
    if not skip_postgres:
        _ensure_postgres()
    if not skip_setup:
        setup_exit = _run_setup(config)
        if setup_exit:
            return setup_exit

    api_pid = _start_process(
        name="api",
        command=build_api_command(config),
        cwd=config.root,
        config=config,
    )
    worker_pid = _start_process(
        name="worker",
        command=build_worker_command(config),
        cwd=config.root,
        config=config,
    )
    web_pid = _start_process(
        name="web",
        command=build_web_command(config),
        cwd=config.web_dir,
        config=config,
    )

    api_ready = _wait_for_listen(config.api_port, timeout_seconds=20)
    web_ready = _wait_for_listen(config.web_port, timeout_seconds=20)
    print(f"api pid={api_pid} listen={api_ready} url=http://{config.host}:{config.api_port}")
    print(f"worker pid={worker_pid} interval=10s")
    print(f"web pid={web_pid} listen={web_ready} url=http://{config.host}:{config.web_port}")
    print(f"logs: {config.log_dir}")
    return 0 if api_ready and web_ready else 1


def stop(config: DevConfig, *, quiet: bool = False) -> int:
    """Stop local dev processes for this checkout."""
    _ensure_runtime_dirs(config)
    pids: set[int] = set()
    for name in ("api", "worker", "web"):
        pid = _read_pid(config, name)
        if pid is not None:
            pids.add(pid)
    pids.update(_listening_pids(config.api_port))
    pids.update(_listening_pids(config.web_port))
    pids.update(
        project_worker_pids(
            _process_rows(),
            root=config.root,
            cwd_lookup=_process_cwd,
        )
    )
    _terminate_pids(sorted(pids))
    for name in ("api", "worker", "web"):
        _pid_file(config, name).unlink(missing_ok=True)
    if not quiet:
        print(f"stopped {len(pids)} process(es)")
    return 0


def status(config: DevConfig) -> int:
    """Print local dev process status."""
    api_pids = _listening_pids(config.api_port)
    web_pids = _listening_pids(config.web_port)
    worker_pids = project_worker_pids(
        _process_rows(),
        root=config.root,
        cwd_lookup=_process_cwd,
    )
    print(f"api port {config.api_port}: {_format_pids(api_pids)}")
    print(f"web port {config.web_port}: {_format_pids(web_pids)}")
    print(f"worker: {_format_pids(worker_pids)}")
    return 0 if api_pids and web_pids and worker_pids else 1


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("start", "stop", "restart", "status"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--api-port", default=8000, type=int)
    parser.add_argument("--web-port", default=3000, type=int)
    parser.add_argument("--no-clean", action="store_true")
    parser.add_argument("--skip-postgres", action="store_true")
    parser.add_argument("--skip-setup", action="store_true")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    config = DevConfig(
        root=root,
        host=args.host,
        api_port=args.api_port,
        web_port=args.web_port,
    )
    if args.command == "start":
        return start(
            config,
            clean=not args.no_clean,
            skip_postgres=args.skip_postgres,
            skip_setup=args.skip_setup,
        )
    if args.command == "stop":
        return stop(config)
    if args.command == "restart":
        stop(config)
        return start(
            config,
            clean=False,
            skip_postgres=args.skip_postgres,
            skip_setup=args.skip_setup,
        )
    return status(config)


def _python_executable(root: Path) -> str:
    """Return the local virtualenv Python executable when available.

    Args:
        root: Repository root containing the ``.venv`` directory.

    Returns:
        str: Path to the virtualenv Python interpreter, falling back to the
            interpreter running this script.
    """
    venv_python = root / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def _ensure_runtime_dirs(config: DevConfig) -> None:
    """Ensure the PID and log directories exist for the dev process group.

    Args:
        config: Dev configuration describing the runtime directory layout.
    """
    config.pid_dir.mkdir(parents=True, exist_ok=True)
    config.log_dir.mkdir(parents=True, exist_ok=True)


def _start_process(
    *,
    name: str,
    command: list[str],
    cwd: Path,
    config: DevConfig,
) -> int:
    """Spawn one background dev process and record its PID.

    Args:
        name: Logical process label used to name the log file and PID file.
        command: Fully-qualified command line to launch the process.
        cwd: Working directory for the spawned process.
        config: Dev configuration that owns the PID and log directories.

    Returns:
        int: PID of the spawned subprocess.
    """
    log_path = config.log_dir / f"{name}.log"
    log_file = log_path.open("ab")
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=with_local_no_proxy(),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    _pid_file(config, name).write_text(str(process.pid), encoding="utf-8")
    return process.pid


def _run_setup(config: DevConfig) -> int:
    """Run migrations and versioned config bootstrap before starting services."""
    for name, command in (
        ("migrate", build_migrate_command(config)),
        ("bootstrap", build_bootstrap_command(config)),
    ):
        result = subprocess.run(
            command,
            cwd=config.root,
            env=with_local_no_proxy(),
            check=False,
        )
        if result.returncode:
            print(f"{name} failed exit={result.returncode}")
            return result.returncode
    return 0


def _ensure_postgres() -> None:
    """Start the docker-compose Postgres service if it is not already healthy."""
    result = subprocess.run(
        ["docker", "ps", "--filter", "name=margin-postgres-1", "--format", "{{.Status}}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if "healthy" in result.stdout:
        return
    subprocess.run(["docker", "compose", "up", "-d", "postgres"], check=True)


def _pid_file(config: DevConfig, name: str) -> Path:
    """Return the path of the PID file for one named dev process.

    Args:
        config: Dev configuration describing the PID directory.
        name: Logical process label.

    Returns:
        Path: Absolute or relative path to the PID file.
    """
    return config.pid_dir / f"{name}.pid"


def _read_pid(config: DevConfig, name: str) -> int | None:
    """Read a persisted PID from disk for one named dev process.

    Args:
        config: Dev configuration describing the PID directory.
        name: Logical process label.

    Returns:
        int | None: The persisted PID, or ``None`` when the file is missing
            or unreadable.
    """
    path = _pid_file(config, name)
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError):
        return None


def _listening_pids(port: int) -> list[int]:
    """Return PIDs currently listening on a TCP port.

    Args:
        port: TCP port number to inspect.

    Returns:
        list[int]: Sorted, de-duplicated list of PIDs listening on the port.
    """
    result = subprocess.run(
        ["lsof", "-tiTCP:" + str(port), "-sTCP:LISTEN", "-n", "-P"],
        check=False,
        capture_output=True,
        text=True,
    )
    pids: list[int] = []
    for line in result.stdout.splitlines():
        try:
            pids.append(int(line.strip()))
        except ValueError:
            continue
    return sorted(set(pids))


def _wait_for_listen(port: int, *, timeout_seconds: float) -> bool:
    """Poll the OS for a listener on a port until one appears or the timeout expires.

    Args:
        port: TCP port number to monitor.
        timeout_seconds: Maximum number of seconds to wait.

    Returns:
        bool: ``True`` if a listener appeared within the timeout, otherwise
            ``False``.
    """
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _listening_pids(port):
            return True
        time.sleep(0.2)
    return False


def _process_rows() -> list[ProcessRow]:
    """List currently running processes with their PID and command line.

    Returns:
        list[ProcessRow]: Parsed ``ps`` rows, skipping lines without a
            numeric PID.
    """
    result = subprocess.run(
        ["ps", "-axo", "pid=,command="],
        check=False,
        capture_output=True,
        text=True,
    )
    rows: list[ProcessRow] = []
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        pid_text, _, command = stripped.partition(" ")
        try:
            rows.append(ProcessRow(int(pid_text), command))
        except ValueError:
            continue
    return rows


def _process_cwd(pid: int) -> Path | None:
    """Return the resolved current working directory for a process.

    Args:
        pid: Process ID to inspect.

    Returns:
        Path | None: Resolved working directory when available, otherwise
            ``None``.
    """
    result = subprocess.run(
        ["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
        check=False,
        capture_output=True,
        text=True,
    )
    for line in result.stdout.splitlines():
        if line.startswith("n"):
            return Path(line[1:]).resolve()
    return None


def _terminate_pids(pids: list[int]) -> None:
    """Terminate a set of PIDs gracefully, escalating to SIGKILL after a grace period.

    Args:
        pids: PIDs to terminate. The current process PID is skipped.
    """
    own_pid = os.getpid()
    for pid in pids:
        if pid == own_pid:
            continue
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            continue
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if all(not _pid_exists(pid) for pid in pids if pid != own_pid):
            return
        time.sleep(0.1)
    for pid in pids:
        if pid == own_pid or not _pid_exists(pid):
            continue
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            continue


def _pid_exists(pid: int) -> bool:
    """Return ``True`` when a process with the given PID is currently alive.

    Args:
        pid: Process ID to probe.

    Returns:
        bool: ``True`` when the process exists (or we lack permission to
            probe it), ``False`` when the OS reports no such process.
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _format_pids(pids: list[int]) -> str:
    """Format a PID list for human-readable status output.

    Args:
        pids: PIDs to format.

    Returns:
        str: Comma-separated PID string or ``"not running"`` when empty.
    """
    if not pids:
        return "not running"
    return ",".join(str(pid) for pid in pids)


if __name__ == "__main__":
    raise SystemExit(main())
