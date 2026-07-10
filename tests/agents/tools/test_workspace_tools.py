"""Security and behavior tests for WorkerAgent workspace tools."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from margin.agents.security.capability import CapabilityToken
from margin.agents.security.policies import (
    DataAccessPolicy,
    ProductionWritePolicy,
    ToolPolicy,
)
from margin.agents.tools.catalog import RegisteredTool, ToolCatalog
from margin.agents.tools.specs import ToolCallRequest
from margin.agents.tools.workspace import register_workspace_tools


def _registered(
    root: Path,
    tool_name: str,
    **options: object,
) -> RegisteredTool:
    catalog = ToolCatalog()
    register_workspace_tools(catalog, root, **options)
    registered = catalog.get(tool_name, "v1")
    assert registered is not None
    return registered


def _call(registered: RegisteredTool, payload: dict[str, object]) -> dict[str, object]:
    token = CapabilityToken(
        token_id="workspace-token",
        run_id="workspace-run",
        issued_by="CodeExpert",
        issued_to="CodeWorker",
        domain="code_execution",
        data_access=(DataAccessPolicy.READ_WORKSPACE,),
        production_write=(ProductionWritePolicy.WRITE_WORKSPACE,),
        tool_policy=(ToolPolicy.WORKSPACE_TOOLS,),
        allowed_artifact_types=("tool_result",),
        allowed_tool_names=(registered.spec.tool_name,),
        expires_at=datetime(2099, 1, 1, tzinfo=UTC),
        max_tool_calls=20,
        max_result_bytes=1_000_000,
    )
    request = ToolCallRequest(
        tool_call_id=f"tc-{registered.spec.tool_name}",
        run_id="workspace-run",
        task_id="workspace-task",
        caller_agent="CodeWorker",
        tool_name=registered.spec.tool_name,
        tool_version=registered.spec.tool_version,
        input_json=payload,
        capability_token=token,
        idempotency_key=f"idem-{registered.spec.tool_name}",
        deadline_ms=120_000,
    )
    return registered.handler(request)


def test_workspace_tools_create_modify_search_and_test_code(tmp_path: Path) -> None:
    write = _registered(tmp_path, "workspace.write_file")
    created = _call(
        write,
        {
            "path": "tests/test_generated.py",
            "content": "def test_generated():\n    assert 1 + 1 == 2\n",
        },
    )

    assert created["ok"] is True
    assert created["created"] is True
    assert created["sha256"]
    assert "tests/test_generated.py" in created["diff"]["unified"]

    modified = _call(
        write,
        {
            "path": "tests/test_generated.py",
            "content": "def test_generated():\n    assert 2 * 3 == 6\n",
            "expected_sha256": created["sha256"],
        },
    )
    assert modified["ok"] is True
    assert modified["created"] is False
    assert modified["previous_sha256"] == created["sha256"]

    stale = _call(
        write,
        {
            "path": "tests/test_generated.py",
            "content": "raise AssertionError\n",
            "expected_sha256": created["sha256"],
        },
    )
    assert stale == {
        "ok": False,
        "error": {
            "code": "hash_conflict",
            "message": "file changed since it was read",
            "current_sha256": modified["sha256"],
        },
    }

    read = _call(
        _registered(tmp_path, "workspace.read_file"),
        {"path": "tests/test_generated.py"},
    )
    assert read["ok"] is True
    assert read["sha256"] == modified["sha256"]
    assert "2 * 3" in read["content"]

    search = _call(
        _registered(tmp_path, "workspace.search"),
        {"path": "tests", "query": "assert", "include_glob": "*.py"},
    )
    assert search["ok"] is True
    assert search["match_count"] == 1
    assert search["matches"][0]["path"] == "tests/test_generated.py"

    listing = _call(_registered(tmp_path, "workspace.list_files"), {"path": "."})
    assert listing["ok"] is True
    assert "tests/test_generated.py" in {entry["path"] for entry in listing["entries"]}

    command = _call(
        _registered(tmp_path, "workspace.run_command", command_timeout_ms=10_000),
        {"argv": ["pytest", "-q", "tests/test_generated.py"]},
    )
    assert command["ok"] is True
    assert command["result"]["status"] == "succeeded"
    assert command["result"]["exit_code"] == 0


def test_workspace_tools_reject_traversal_absolute_and_sensitive_paths(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("TOKEN=hidden", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("hidden", encoding="utf-8")
    read = _registered(tmp_path, "workspace.read_file")
    write = _registered(tmp_path, "workspace.write_file")

    for path in ("../outside.py", str(tmp_path / "inside.py"), ".env", "secret.txt"):
        result = _call(read, {"path": path})
        assert result["ok"] is False
        assert result["error"]["code"] == "path_forbidden"

    result = _call(write, {"path": "nested/../../outside.py", "content": "unsafe"})
    assert result["ok"] is False
    assert result["error"]["code"] == "path_forbidden"
    assert not (tmp_path.parent / "outside.py").exists()

    listing = _call(_registered(tmp_path, "workspace.list_files"), {"path": "."})
    listed_paths = {entry["path"] for entry in listing["entries"]}
    assert ".env" not in listed_paths
    assert "secret.txt" not in listed_paths


def test_workspace_tools_reject_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "data.py").write_text("outside = True\n", encoding="utf-8")
    (root / "escape").symlink_to(outside, target_is_directory=True)

    read = _call(
        _registered(root, "workspace.read_file"),
        {"path": "escape/data.py"},
    )
    write = _call(
        _registered(root, "workspace.write_file"),
        {"path": "escape/new.py", "content": "unsafe = True\n"},
    )
    command = _call(
        _registered(root, "workspace.run_command"),
        {"argv": ["git", "status"], "cwd": "escape"},
    )

    assert read["ok"] is False and read["error"]["code"] == "path_forbidden"
    assert write["ok"] is False and write["error"]["code"] == "path_forbidden"
    assert command["ok"] is False and command["error"]["code"] == "path_forbidden"
    assert not (outside / "new.py").exists()


def test_write_rejects_binary_source_without_overwriting_it(tmp_path: Path) -> None:
    original = b"\xff\xfe\x00source"
    (tmp_path / "binary.py").write_bytes(original)
    write = _registered(tmp_path, "workspace.write_file")

    result = _call(write, {"path": "binary.py", "content": "replaced = True\n"})

    assert result["ok"] is False
    assert result["error"]["code"] == "file_not_utf8"
    assert (tmp_path / "binary.py").read_bytes() == original


def test_run_command_rejects_shell_and_path_injection(tmp_path: Path) -> None:
    marker = tmp_path / "injected"
    run = _registered(tmp_path, "workspace.run_command")

    string_command = _call(run, {"argv": f"pytest -q; touch {marker}"})
    shell_tokens = _call(run, {"argv": ["pytest", "-q", ";", "touch", "injected"]})
    shell = _call(run, {"argv": ["bash", "-c", "touch injected"]})
    outside_path = _call(run, {"argv": ["pytest", "../outside"]})
    network = _call(run, {"argv": ["pytest", "https://example.com/test.py"]})

    assert string_command["error"]["code"] == "invalid_input"
    assert shell_tokens["error"]["code"] == "command_forbidden"
    assert shell["error"]["code"] == "command_not_allowed"
    assert outside_path["error"]["code"] == "path_forbidden"
    assert network["error"]["code"] == "command_forbidden"
    assert not marker.exists()


def test_run_command_times_out_and_caps_output(tmp_path: Path) -> None:
    (tmp_path / "test_slow.py").write_text(
        "import time\n\ndef test_slow():\n    print('x' * 10000, flush=True)\n    time.sleep(5)\n",
        encoding="utf-8",
    )
    run = _registered(
        tmp_path,
        "workspace.run_command",
        command_timeout_ms=500,
        max_command_output_bytes=512,
    )

    result = _call(
        run,
        {
            "argv": ["pytest", "-q", "-s", "test_slow.py"],
            "timeout_ms": 500,
            "max_output_bytes": 512,
        },
    )

    assert result["ok"] is False
    assert result["result"]["status"] == "timed_out"
    assert result["result"]["timed_out"] is True
    assert result["result"]["captured_output_bytes"] <= 512
    assert result["result"]["stdout_truncated"] is True


def test_workspace_specs_require_dedicated_capabilities(tmp_path: Path) -> None:
    read = _registered(tmp_path, "workspace.read_file").spec
    write = _registered(tmp_path, "workspace.write_file").spec
    run = _registered(tmp_path, "workspace.run_command").spec

    assert read.required_data_access == (DataAccessPolicy.READ_WORKSPACE,)
    assert read.required_write_policy == ()
    assert read.required_tool_policy == (ToolPolicy.WORKSPACE_TOOLS,)
    assert write.required_write_policy == (ProductionWritePolicy.WRITE_WORKSPACE,)
    assert run.required_write_policy == (ProductionWritePolicy.WRITE_WORKSPACE,)
