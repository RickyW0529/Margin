"""Constrained source-workspace tools for code-capable WorkerAgents."""

from __future__ import annotations

import difflib
import fnmatch
import hashlib
import os
import re
import shutil
import signal
import stat
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from typing import Any

from margin.agents.security.policies import (
    DataAccessPolicy,
    ProductionWritePolicy,
    ToolPolicy,
)
from margin.agents.tools.catalog import ToolCatalog
from margin.agents.tools.specs import ToolCallRequest, ToolSpec

WORKSPACE_TOOL_VERSION = "v1"

DEFAULT_ALLOWED_COMMAND_PREFIXES: tuple[tuple[str, ...], ...] = (
    ("ruff", "check"),
    ("pytest",),
    ("python", "-m", "pytest"),
    ("python3", "-m", "pytest"),
    ("uv", "run", "pytest"),
    ("uv", "run", "ruff", "check"),
    ("tox",),
    ("mypy",),
    ("pyright",),
    ("npm", "test"),
    ("npm", "run", "lint"),
    ("npm", "run", "test"),
    ("npm", "run", "build"),
    ("npm", "run", "typecheck"),
    ("cargo", "test"),
    ("cargo", "check"),
    ("cargo", "build"),
    ("make", "test"),
    ("make", "lint"),
    ("make", "build"),
    ("git", "status"),
    ("git", "diff"),
    ("git", "show"),
    ("git", "log"),
    ("git", "rev-parse"),
)

_SENSITIVE_COMPONENTS = frozenset(
    {
        ".aws",
        ".git",
        ".gnupg",
        ".hg",
        ".netrc",
        ".npmrc",
        ".pypirc",
        ".ssh",
        ".svn",
        "credential",
        "credentials",
        "secret",
        "secrets",
    }
)
_SENSITIVE_SUFFIXES = frozenset({".key", ".p12", ".pfx", ".pem"})
_SENSITIVE_PREFIXES = (".env", "credential.", "credentials.", "secret.", "secrets.")
_FORBIDDEN_EXECUTABLES = frozenset(
    {
        "bash",
        "cmd",
        "curl",
        "dash",
        "dd",
        "fish",
        "ftp",
        "nc",
        "ncat",
        "netcat",
        "powershell",
        "pwsh",
        "rm",
        "rmdir",
        "scp",
        "sftp",
        "sh",
        "ssh",
        "sudo",
        "telnet",
        "wget",
        "zsh",
    }
)
_SAFE_GIT_SUBCOMMANDS = frozenset(
    {"diff", "grep", "log", "ls-files", "rev-parse", "show", "status"}
)
_FORBIDDEN_PYTHON_MODULES = frozenset(
    {"ensurepip", "http.server", "pip", "venv", "webbrowser"}
)
_SHELL_META_RE = re.compile(r"[;&|`\r\n\x00]|\$\(")
_NETWORK_URI_RE = re.compile(r"(?:ftp|https?|ssh)://", re.IGNORECASE)
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_MAX_ARGUMENTS = 128
_MAX_ARGUMENT_CHARS = 32_768
_MAX_QUERY_CHARS = 2_000
_MAX_MATCH_LINE_CHARS = 1_000


class WorkspaceToolError(Exception):
    """Expected, safely reportable workspace-tool rejection."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    def as_output(self) -> dict[str, Any]:
        return {
            "ok": False,
            "error": {"code": self.code, "message": self.message, **self.details},
        }


@dataclass(frozen=True)
class _WorkspaceConfig:
    root: Path
    allowed_command_prefixes: tuple[tuple[str, ...], ...]
    max_file_bytes: int
    max_diff_bytes: int
    max_list_entries: int
    max_search_results: int
    command_timeout_ms: int
    max_command_output_bytes: int


class _WorkspaceTools:
    def __init__(self, config: _WorkspaceConfig) -> None:
        self._config = config
        self._write_lock = threading.RLock()

    def list_files(self, request: ToolCallRequest) -> dict[str, Any]:
        return self._guard(lambda: self._list_files(request.input_json))

    def read_file(self, request: ToolCallRequest) -> dict[str, Any]:
        return self._guard(lambda: self._read_file(request.input_json))

    def search(self, request: ToolCallRequest) -> dict[str, Any]:
        return self._guard(lambda: self._search(request.input_json))

    def write_file(self, request: ToolCallRequest) -> dict[str, Any]:
        return self._guard(lambda: self._write_file(request.input_json))

    def run_command(self, request: ToolCallRequest) -> dict[str, Any]:
        return self._guard(
            lambda: self._run_command(
                request.input_json,
                deadline_ms=request.deadline_ms,
            )
        )

    @staticmethod
    def _guard(operation: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        try:
            return operation()
        except WorkspaceToolError as exc:
            return exc.as_output()

    def _list_files(self, payload: dict[str, Any]) -> dict[str, Any]:
        base = _resolve_workspace_path(
            self._config.root,
            payload.get("path", "."),
            must_exist=True,
        )
        if not base.is_dir():
            raise WorkspaceToolError("not_a_directory", "path must identify a directory")
        recursive = _optional_bool(payload, "recursive", default=True)
        limit = _bounded_positive_int(
            payload,
            "limit",
            default=self._config.max_list_entries,
            maximum=self._config.max_list_entries,
        )
        entries: list[dict[str, Any]] = []
        skipped_sensitive = 0
        skipped_symlinks = 0
        stack = [base]
        truncated = False
        while stack:
            directory = stack.pop()
            try:
                children = sorted(directory.iterdir(), key=lambda item: item.name.casefold())
            except OSError as exc:
                raise WorkspaceToolError("path_unreadable", "directory cannot be read") from exc
            child_directories: list[Path] = []
            for child in children:
                relative = child.relative_to(self._config.root)
                if _contains_sensitive_component(relative):
                    skipped_sensitive += 1
                    continue
                if child.is_symlink():
                    skipped_symlinks += 1
                    continue
                try:
                    child_stat = child.stat()
                except OSError:
                    continue
                if len(entries) >= limit:
                    truncated = True
                    stack.clear()
                    break
                if stat.S_ISDIR(child_stat.st_mode):
                    entries.append({"path": relative.as_posix(), "type": "directory"})
                    if recursive:
                        child_directories.append(child)
                elif stat.S_ISREG(child_stat.st_mode):
                    entries.append(
                        {
                            "path": relative.as_posix(),
                            "type": "file",
                            "size_bytes": child_stat.st_size,
                        }
                    )
            if truncated:
                break
            stack.extend(reversed(child_directories))
        return {
            "ok": True,
            "path": _display_path(self._config.root, base),
            "entries": entries,
            "entry_count": len(entries),
            "truncated": truncated,
            "skipped_sensitive": skipped_sensitive,
            "skipped_symlinks": skipped_symlinks,
        }

    def _read_file(self, payload: dict[str, Any]) -> dict[str, Any]:
        path = _resolve_workspace_path(
            self._config.root,
            _required_string(payload, "path"),
            must_exist=True,
        )
        content = _read_regular_file(path, self._config.max_file_bytes)
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise WorkspaceToolError("file_not_utf8", "file must contain UTF-8 text") from exc
        return {
            "ok": True,
            "path": _display_path(self._config.root, path),
            "content": text,
            "size_bytes": len(content),
            "sha256": _sha256(content),
        }

    def _search(self, payload: dict[str, Any]) -> dict[str, Any]:
        query = _required_string(payload, "query")
        if not query or len(query) > _MAX_QUERY_CHARS:
            raise WorkspaceToolError(
                "invalid_input",
                f"query must contain between 1 and {_MAX_QUERY_CHARS} characters",
            )
        base = _resolve_workspace_path(
            self._config.root,
            payload.get("path", "."),
            must_exist=True,
        )
        case_sensitive = _optional_bool(payload, "case_sensitive", default=True)
        include_glob = payload.get("include_glob")
        if include_glob is not None and not isinstance(include_glob, str):
            raise WorkspaceToolError("invalid_input", "include_glob must be a string")
        limit = _bounded_positive_int(
            payload,
            "limit",
            default=self._config.max_search_results,
            maximum=self._config.max_search_results,
        )
        files = [base] if base.is_file() else self._iter_search_files(base)
        needle = query if case_sensitive else query.casefold()
        matches: list[dict[str, Any]] = []
        files_scanned = 0
        files_skipped = 0
        truncated = False
        for path in files:
            relative = path.relative_to(self._config.root).as_posix()
            if include_glob and not (
                fnmatch.fnmatch(relative, include_glob)
                or fnmatch.fnmatch(path.name, include_glob)
            ):
                continue
            try:
                content = _read_regular_file(path, self._config.max_file_bytes)
                text = content.decode("utf-8")
            except WorkspaceToolError:
                files_skipped += 1
                continue
            except UnicodeDecodeError:
                files_skipped += 1
                continue
            files_scanned += 1
            for line_number, line in enumerate(text.splitlines(), start=1):
                haystack = line if case_sensitive else line.casefold()
                offset = 0
                while True:
                    column = haystack.find(needle, offset)
                    if column < 0:
                        break
                    matches.append(
                        {
                            "path": relative,
                            "line": line_number,
                            "column": column + 1,
                            "text": line[:_MAX_MATCH_LINE_CHARS],
                            "text_truncated": len(line) > _MAX_MATCH_LINE_CHARS,
                        }
                    )
                    if len(matches) >= limit:
                        truncated = True
                        break
                    offset = column + max(len(needle), 1)
                if truncated:
                    break
            if truncated:
                break
        return {
            "ok": True,
            "query": query,
            "matches": matches,
            "match_count": len(matches),
            "files_scanned": files_scanned,
            "files_skipped": files_skipped,
            "truncated": truncated,
        }

    def _iter_search_files(self, base: Path) -> list[Path]:
        files: list[Path] = []
        stack = [base]
        while stack:
            directory = stack.pop()
            try:
                children = sorted(directory.iterdir(), key=lambda item: item.name.casefold())
            except OSError:
                continue
            for child in reversed(children):
                relative = child.relative_to(self._config.root)
                if _contains_sensitive_component(relative) or child.is_symlink():
                    continue
                if child.is_dir():
                    stack.append(child)
                elif child.is_file():
                    files.append(child)
        files.sort(key=lambda item: item.relative_to(self._config.root).as_posix())
        return files

    def _write_file(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw_path = _required_string(payload, "path")
        content_text = _required_string(payload, "content", allow_empty=True)
        content = content_text.encode("utf-8")
        if len(content) > self._config.max_file_bytes:
            raise WorkspaceToolError(
                "file_too_large",
                "file exceeds the configured write limit",
                max_bytes=self._config.max_file_bytes,
            )
        expected_sha256 = payload.get("expected_sha256")
        if expected_sha256 is not None and (
            not isinstance(expected_sha256, str)
            or _SHA256_RE.fullmatch(expected_sha256.casefold()) is None
        ):
            raise WorkspaceToolError(
                "invalid_input", "expected_sha256 must be a lowercase SHA-256 digest"
            )
        path = _resolve_workspace_path(
            self._config.root,
            raw_path,
            must_exist=False,
            reject_symlinks=True,
        )
        with self._write_lock:
            parent = path.parent
            _ensure_directory(parent, self._config.root)
            _reject_symlink_chain(self._config.root, path)
            existed = path.exists()
            old_content = (
                _read_regular_file(path, self._config.max_file_bytes) if existed else b""
            )
            try:
                old_text = old_content.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise WorkspaceToolError(
                    "file_not_utf8", "existing file must contain UTF-8 text"
                ) from exc
            old_sha256 = _sha256(old_content) if existed else None
            if existed and expected_sha256 is None:
                raise WorkspaceToolError(
                    "expected_hash_required",
                    "expected_sha256 is required when modifying an existing file",
                    current_sha256=old_sha256,
                )
            if expected_sha256 is not None and expected_sha256.casefold() != old_sha256:
                raise WorkspaceToolError(
                    "hash_conflict",
                    "file changed since it was read",
                    current_sha256=old_sha256,
                )
            _atomic_write(path, content, old_mode=_file_mode(path) if existed else None)
        relative = _display_path(self._config.root, path)
        diff = "".join(
            difflib.unified_diff(
                old_text.splitlines(keepends=True),
                content_text.splitlines(keepends=True),
                fromfile=f"a/{relative}",
                tofile=f"b/{relative}",
            )
        )
        limited_diff, diff_truncated = _limit_utf8(diff, self._config.max_diff_bytes)
        return {
            "ok": True,
            "path": relative,
            "created": not existed,
            "bytes_written": len(content),
            "previous_sha256": old_sha256,
            "sha256": _sha256(content),
            "diff": {"unified": limited_diff, "truncated": diff_truncated},
        }

    def _run_command(
        self,
        payload: dict[str, Any],
        *,
        deadline_ms: int,
    ) -> dict[str, Any]:
        argv = _validated_argv(payload.get("argv"))
        if not _matches_prefix(argv, self._config.allowed_command_prefixes):
            raise WorkspaceToolError(
                "command_not_allowed", "command does not match an allowed argv prefix"
            )
        _validate_command_semantics(argv)
        cwd = _resolve_workspace_path(
            self._config.root,
            payload.get("cwd", "."),
            must_exist=True,
        )
        if not cwd.is_dir():
            raise WorkspaceToolError("not_a_directory", "cwd must identify a directory")
        _validate_command_paths(argv, root=self._config.root, cwd=cwd)
        effective_timeout_ms = min(self._config.command_timeout_ms, deadline_ms)
        timeout_ms = _bounded_positive_int(
            payload,
            "timeout_ms",
            default=effective_timeout_ms,
            maximum=effective_timeout_ms,
        )
        output_limit = _bounded_positive_int(
            payload,
            "max_output_bytes",
            default=self._config.max_command_output_bytes,
            maximum=self._config.max_command_output_bytes,
        )
        executable = _resolve_executable(argv[0], root=self._config.root, cwd=cwd)
        command = [str(executable), *argv[1:]]
        started = time.monotonic()
        capture = _BoundedOutputCapture(limit=output_limit)
        with tempfile.TemporaryDirectory(prefix="margin-workspace-command-") as temp_home:
            try:
                process = subprocess.Popen(  # noqa: S603 - argv and executable are allowlisted
                    command,
                    cwd=cwd,
                    env=_command_environment(Path(temp_home)),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    shell=False,
                    start_new_session=os.name == "posix",
                )
            except OSError as exc:
                raise WorkspaceToolError(
                    "command_unavailable", "allowed command could not be started"
                ) from exc
            readers = capture.start_readers(process)
            timed_out = False
            try:
                process.wait(timeout=timeout_ms / 1000)
            except subprocess.TimeoutExpired:
                timed_out = True
                _terminate_process(process)
            finally:
                process.wait()
                for reader in readers:
                    reader.join(timeout=2)
        duration_ms = max(0, int((time.monotonic() - started) * 1000))
        stdout, stderr = capture.text()
        status_name = (
            "timed_out"
            if timed_out
            else ("succeeded" if process.returncode == 0 else "failed")
        )
        return {
            "ok": not timed_out and process.returncode == 0,
            "command": {"argv": argv, "cwd": _display_path(self._config.root, cwd)},
            "result": {
                "status": status_name,
                "exit_code": None if timed_out else process.returncode,
                "timed_out": timed_out,
                "duration_ms": duration_ms,
                "stdout": stdout,
                "stderr": stderr,
                "stdout_truncated": capture.stdout_truncated,
                "stderr_truncated": capture.stderr_truncated,
                "captured_output_bytes": capture.captured_bytes,
            },
        }


@dataclass
class _BoundedOutputCapture:
    limit: int
    stdout: bytearray = field(default_factory=bytearray)
    stderr: bytearray = field(default_factory=bytearray)
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    captured_bytes: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def start_readers(self, process: subprocess.Popen[bytes]) -> tuple[threading.Thread, ...]:
        assert process.stdout is not None
        assert process.stderr is not None
        readers = (
            threading.Thread(
                target=self._drain,
                args=("stdout", process.stdout),
                daemon=True,
            ),
            threading.Thread(
                target=self._drain,
                args=("stderr", process.stderr),
                daemon=True,
            ),
        )
        for reader in readers:
            reader.start()
        return readers

    def _drain(self, stream_name: str, stream: Any) -> None:
        target = self.stdout if stream_name == "stdout" else self.stderr
        while chunk := stream.read(8192):
            with self._lock:
                remaining = max(0, self.limit - self.captured_bytes)
                accepted = chunk[:remaining]
                target.extend(accepted)
                self.captured_bytes += len(accepted)
                if len(accepted) < len(chunk):
                    if stream_name == "stdout":
                        self.stdout_truncated = True
                    else:
                        self.stderr_truncated = True
        stream.close()

    def text(self) -> tuple[str, str]:
        with self._lock:
            return (
                self.stdout.decode("utf-8", errors="replace"),
                self.stderr.decode("utf-8", errors="replace"),
            )


def register_workspace_tools(
    catalog: ToolCatalog,
    root: str | Path,
    *,
    allowed_command_prefixes: Iterable[Sequence[str]] | None = None,
    max_file_bytes: int = 512_000,
    max_diff_bytes: int = 64_000,
    max_list_entries: int = 1_000,
    max_search_results: int = 200,
    command_timeout_ms: int = 120_000,
    max_command_output_bytes: int = 128_000,
) -> None:
    """Register five tools rooted at one explicitly supplied source workspace."""
    resolved_root = Path(root).expanduser().resolve(strict=True)
    if not resolved_root.is_dir():
        raise ValueError("workspace root must be an existing directory")
    positive_options = {
        "max_file_bytes": max_file_bytes,
        "max_diff_bytes": max_diff_bytes,
        "max_list_entries": max_list_entries,
        "max_search_results": max_search_results,
        "command_timeout_ms": command_timeout_ms,
        "max_command_output_bytes": max_command_output_bytes,
    }
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value <= 0
        for value in positive_options.values()
    ):
        raise ValueError("workspace limits must be positive integers")
    prefixes = _normalize_prefixes(allowed_command_prefixes)
    tools = _WorkspaceTools(
        _WorkspaceConfig(
            root=resolved_root,
            allowed_command_prefixes=prefixes,
            max_file_bytes=max_file_bytes,
            max_diff_bytes=max_diff_bytes,
            max_list_entries=max_list_entries,
            max_search_results=max_search_results,
            command_timeout_ms=command_timeout_ms,
            max_command_output_bytes=max_command_output_bytes,
        )
    )
    handlers = {
        "workspace.list_files": tools.list_files,
        "workspace.read_file": tools.read_file,
        "workspace.search": tools.search,
        "workspace.write_file": tools.write_file,
        "workspace.run_command": tools.run_command,
    }
    for tool_name, handler in handlers.items():
        catalog.register(
            _workspace_spec(
                tool_name,
                mutates_state=tool_name in {"workspace.write_file", "workspace.run_command"},
                timeout_ms=(
                    command_timeout_ms + 1_000
                    if tool_name == "workspace.run_command"
                    else 30_000
                ),
                max_output_bytes=(
                    max_command_output_bytes * 6 + 16_384
                    if tool_name == "workspace.run_command"
                    else max_diff_bytes * 6 + 16_384
                    if tool_name == "workspace.write_file"
                    else max(max_file_bytes * 6 + 16_384, 512_000)
                ),
            ),
            handler,
        )


def _workspace_spec(
    tool_name: str,
    *,
    mutates_state: bool,
    timeout_ms: int,
    max_output_bytes: int,
) -> ToolSpec:
    return ToolSpec(
        tool_name=tool_name,
        tool_version=WORKSPACE_TOOL_VERSION,
        description=f"Constrained source workspace operation: {tool_name}.",
        owner_domain="code_execution",
        input_schema_ref=f"schema.{tool_name}.input.v1",
        output_schema_ref=f"schema.{tool_name}.output.v1",
        input_schema=_workspace_input_schema(tool_name),
        output_schema={"type": "object"},
        required_data_access=(DataAccessPolicy.READ_WORKSPACE,),
        required_write_policy=(
            (ProductionWritePolicy.WRITE_WORKSPACE,) if mutates_state else ()
        ),
        required_tool_policy=(ToolPolicy.WORKSPACE_TOOLS,),
        idempotent=not mutates_state,
        mutates_state=mutates_state,
        timeout_ms=timeout_ms,
        max_output_bytes=max_output_bytes,
        returns_raw_payload=False,
        allowed_runtimes=("langgraph",),
    )


def _workspace_input_schema(tool_name: str) -> dict[str, Any]:
    schemas: dict[str, dict[str, Any]] = {
        "workspace.list_files": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "recursive": {"type": "boolean"},
                "limit": {"type": "integer"},
            },
        },
        "workspace.read_file": {
            "type": "object",
            "required": ["path"],
            "properties": {"path": {"type": "string"}},
        },
        "workspace.search": {
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string"},
                "path": {"type": "string"},
                "include_glob": {"type": "string"},
                "case_sensitive": {"type": "boolean"},
                "limit": {"type": "integer"},
            },
        },
        "workspace.write_file": {
            "type": "object",
            "required": ["path", "content"],
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
                "expected_sha256": {"type": "string"},
            },
        },
        "workspace.run_command": {
            "type": "object",
            "required": ["argv"],
            "properties": {
                "argv": {"type": "array", "items": {"type": "string"}},
                "cwd": {"type": "string"},
                "timeout_ms": {"type": "integer"},
                "max_output_bytes": {"type": "integer"},
            },
        },
    }
    return schemas[tool_name]


def _normalize_prefixes(
    prefixes: Iterable[Sequence[str]] | None,
) -> tuple[tuple[str, ...], ...]:
    source = DEFAULT_ALLOWED_COMMAND_PREFIXES if prefixes is None else prefixes
    normalized: list[tuple[str, ...]] = []
    for prefix in source:
        if isinstance(prefix, str):
            raise ValueError("command prefixes must be argv sequences")
        value = tuple(prefix)
        if not value or any(not isinstance(item, str) or not item for item in value):
            raise ValueError("command prefixes must contain non-empty strings")
        try:
            _validate_command_semantics(value)
        except WorkspaceToolError as exc:
            raise ValueError(f"unsafe command prefix: {exc.code}") from exc
        normalized.append(value)
    if not normalized:
        raise ValueError("at least one command prefix is required")
    return tuple(normalized)


def _validated_argv(value: object) -> list[str]:
    if not isinstance(value, list) or not value:
        raise WorkspaceToolError("invalid_input", "argv must be a non-empty JSON array")
    if len(value) > _MAX_ARGUMENTS or any(not isinstance(item, str) or not item for item in value):
        raise WorkspaceToolError(
            "invalid_input", "argv must contain a bounded list of non-empty strings"
        )
    argv = list(value)
    if sum(len(item) for item in argv) > _MAX_ARGUMENT_CHARS:
        raise WorkspaceToolError("invalid_input", "argv exceeds the configured size limit")
    return argv


def _matches_prefix(argv: Sequence[str], prefixes: Sequence[Sequence[str]]) -> bool:
    return any(tuple(argv[: len(prefix)]) == tuple(prefix) for prefix in prefixes)


def _validate_command_semantics(argv: Sequence[str]) -> None:
    executable = Path(argv[0]).name.casefold()
    if executable in _FORBIDDEN_EXECUTABLES:
        raise WorkspaceToolError("command_forbidden", "network or destructive command denied")
    if any(_SHELL_META_RE.search(argument) for argument in argv):
        raise WorkspaceToolError("command_forbidden", "shell control characters are not allowed")
    if any(_NETWORK_URI_RE.search(argument) for argument in argv):
        raise WorkspaceToolError("command_forbidden", "network locations are not allowed")
    if executable == "git" and (len(argv) < 2 or argv[1].casefold() not in _SAFE_GIT_SUBCOMMANDS):
        raise WorkspaceToolError("command_forbidden", "only read-only git commands are allowed")
    if executable in {"python", "python3"}:
        if "-c" in argv or "-" in argv:
            raise WorkspaceToolError("command_forbidden", "inline interpreter code is not allowed")
        if len(argv) >= 3 and argv[1] == "-m" and argv[2].casefold() in _FORBIDDEN_PYTHON_MODULES:
            raise WorkspaceToolError("command_forbidden", "network or installer module denied")


def _validate_command_paths(argv: Sequence[str], *, root: Path, cwd: Path) -> None:
    for argument in argv[1:]:
        candidate = argument.split("=", 1)[1] if "=" in argument else argument
        if not candidate or candidate.startswith("-"):
            continue
        windows_path = PureWindowsPath(candidate)
        path = Path(candidate)
        if path.is_absolute() or windows_path.is_absolute():
            raise WorkspaceToolError("path_forbidden", "absolute command paths are not allowed")
        normalized_parts = PureWindowsPath(candidate.replace("/", "\\")).parts
        if ".." in path.parts or ".." in normalized_parts:
            raise WorkspaceToolError("path_forbidden", "parent path traversal is not allowed")
        if _contains_sensitive_component(path):
            raise WorkspaceToolError("path_forbidden", "sensitive workspace path denied")
        looks_like_path = "/" in candidate or "\\" in candidate or (cwd / path).exists()
        if looks_like_path:
            resolved = (cwd / path).resolve(strict=False)
            _ensure_within_root(root, resolved)
            relative = resolved.relative_to(root)
            if _contains_sensitive_component(relative):
                raise WorkspaceToolError("path_forbidden", "sensitive workspace path denied")


def _resolve_executable(command: str, *, root: Path, cwd: Path) -> Path:
    if "/" in command or "\\" in command:
        command_path = Path(command)
        if command_path.is_absolute() or PureWindowsPath(command).is_absolute():
            raise WorkspaceToolError("path_forbidden", "absolute command paths are not allowed")
        try:
            relative_command = (cwd / command_path).relative_to(root)
        except ValueError as exc:
            raise WorkspaceToolError(
                "path_forbidden", "workspace boundary escape denied"
            ) from exc
        executable = _resolve_workspace_path(root, relative_command.as_posix(), must_exist=True)
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise WorkspaceToolError("command_unavailable", "allowed command is not executable")
        return executable
    executable_path = shutil.which(command, path=os.environ.get("PATH"))
    if executable_path is None:
        raise WorkspaceToolError("command_unavailable", "allowed command is not installed")
    return Path(executable_path).resolve(strict=True)


def _command_environment(temp_home: Path) -> dict[str, str]:
    environment = {
        "HOME": str(temp_home),
        "PATH": os.environ.get("PATH", os.defpath),
        "PYTHONNOUSERSITE": "1",
        "PIP_NO_INDEX": "1",
        "UV_OFFLINE": "1",
        "npm_config_offline": "true",
        "CARGO_NET_OFFLINE": "true",
        "GIT_TERMINAL_PROMPT": "0",
        "HTTP_PROXY": "http://127.0.0.1:9",
        "HTTPS_PROXY": "http://127.0.0.1:9",
        "ALL_PROXY": "http://127.0.0.1:9",
        "http_proxy": "http://127.0.0.1:9",
        "https_proxy": "http://127.0.0.1:9",
        "all_proxy": "http://127.0.0.1:9",
        "NO_PROXY": "",
    }
    for name in ("LANG", "LC_ALL", "SYSTEMROOT", "TMPDIR", "VIRTUAL_ENV"):
        value = os.environ.get(name)
        if value:
            environment[name] = value
    return environment


def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except ProcessLookupError:
        return


def _resolve_workspace_path(
    root: Path,
    raw_path: object,
    *,
    must_exist: bool,
    reject_symlinks: bool = False,
) -> Path:
    relative = _relative_path(raw_path)
    candidate = root / relative
    if reject_symlinks:
        _reject_symlink_chain(root, candidate)
    try:
        resolved = candidate.resolve(strict=must_exist)
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise WorkspaceToolError("path_not_found", "workspace path does not exist") from exc
    _ensure_within_root(root, resolved)
    if _contains_sensitive_component(resolved.relative_to(root)):
        raise WorkspaceToolError("path_forbidden", "sensitive workspace path denied")
    return resolved


def _relative_path(raw_path: object) -> Path:
    if not isinstance(raw_path, str) or not raw_path or "\x00" in raw_path:
        raise WorkspaceToolError("invalid_input", "path must be a non-empty relative string")
    path = Path(raw_path)
    windows_path = PureWindowsPath(raw_path)
    if path.is_absolute() or windows_path.is_absolute():
        raise WorkspaceToolError("path_forbidden", "absolute paths are not allowed")
    windows_parts = PureWindowsPath(raw_path.replace("/", "\\")).parts
    if ".." in path.parts or ".." in windows_parts:
        raise WorkspaceToolError("path_forbidden", "parent path traversal is not allowed")
    if _contains_sensitive_component(path):
        raise WorkspaceToolError("path_forbidden", "sensitive workspace path denied")
    return path


def _contains_sensitive_component(path: Path) -> bool:
    for component in path.parts:
        lowered = component.casefold()
        if lowered in {"", "."}:
            continue
        if lowered in _SENSITIVE_COMPONENTS or lowered.startswith(_SENSITIVE_PREFIXES):
            return True
        if Path(lowered).suffix in _SENSITIVE_SUFFIXES:
            return True
    return False


def _ensure_within_root(root: Path, path: Path) -> None:
    if not path.is_relative_to(root):
        raise WorkspaceToolError("path_forbidden", "workspace boundary escape denied")


def _reject_symlink_chain(root: Path, candidate: Path) -> None:
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise WorkspaceToolError("path_forbidden", "workspace boundary escape denied") from exc
    current = root
    for component in relative.parts:
        current /= component
        try:
            if current.is_symlink():
                raise WorkspaceToolError("path_forbidden", "symlink writes are not allowed")
        except OSError as exc:
            raise WorkspaceToolError(
                "path_unreadable", "workspace path cannot be inspected"
            ) from exc
        if not current.exists():
            break


def _read_regular_file(path: Path, max_bytes: int) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise WorkspaceToolError("path_not_found", "workspace path does not exist") from exc
    except OSError as exc:
        raise WorkspaceToolError("path_unreadable", "file cannot be opened safely") from exc
    try:
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            raise WorkspaceToolError("not_a_file", "path must identify a regular file")
        if file_stat.st_size > max_bytes:
            raise WorkspaceToolError(
                "file_too_large", "file exceeds the configured read limit", max_bytes=max_bytes
            )
        with os.fdopen(descriptor, "rb", closefd=False) as file_handle:
            content = file_handle.read(max_bytes + 1)
        if len(content) > max_bytes:
            raise WorkspaceToolError(
                "file_too_large", "file exceeds the configured read limit", max_bytes=max_bytes
            )
        return content
    finally:
        os.close(descriptor)


def _ensure_directory(directory: Path, root: Path) -> None:
    _ensure_within_root(root, directory.resolve(strict=False))
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise WorkspaceToolError("path_unwritable", "parent directory cannot be created") from exc
    _reject_symlink_chain(root, directory)


def _atomic_write(path: Path, content: bytes, *, old_mode: int | None) -> None:
    descriptor, temp_name = tempfile.mkstemp(prefix=".margin-workspace-", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        os.fchmod(descriptor, old_mode if old_mode is not None else 0o644)
        with os.fdopen(descriptor, "wb", closefd=False) as file_handle:
            file_handle.write(content)
            file_handle.flush()
            os.fsync(file_handle.fileno())
        os.close(descriptor)
        descriptor = -1
        os.replace(temp_path, path)
        try:
            directory_descriptor = os.open(path.parent, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except OSError as exc:
        raise WorkspaceToolError("path_unwritable", "file could not be written atomically") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temp_path.unlink(missing_ok=True)


def _file_mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _required_string(
    payload: dict[str, Any],
    key: str,
    *,
    allow_empty: bool = False,
) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or (not allow_empty and not value):
        raise WorkspaceToolError("invalid_input", f"{key} must be a string")
    return value


def _optional_bool(payload: dict[str, Any], key: str, *, default: bool) -> bool:
    value = payload.get(key, default)
    if not isinstance(value, bool):
        raise WorkspaceToolError("invalid_input", f"{key} must be a boolean")
    return value


def _bounded_positive_int(
    payload: dict[str, Any],
    key: str,
    *,
    default: int,
    maximum: int,
) -> int:
    value = payload.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0 or value > maximum:
        raise WorkspaceToolError(
            "invalid_input", f"{key} must be an integer between 1 and {maximum}"
        )
    return value


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _display_path(root: Path, path: Path) -> str:
    relative = path.relative_to(root)
    return relative.as_posix() or "."


def _limit_utf8(value: str, max_bytes: int) -> tuple[str, bool]:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value, False
    return encoded[:max_bytes].decode("utf-8", errors="ignore"), True
