"""Architecture contracts for the v1 agent migration."""

from __future__ import annotations

import tomllib
from pathlib import Path


def test_langgraph_dependency_is_bounded_to_reviewed_major_range() -> None:
    """Keep graph orchestration behavior inside the reviewed major range."""
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    dependencies = pyproject["project"]["dependencies"]

    assert "langgraph>=1.0,<1.3" in dependencies
    assert "langgraph>=0.2" not in dependencies


def test_langchain_is_not_used_in_agent_runtime() -> None:
    """Agent runtime should use LangGraph orchestration, not LangChain adapters."""
    source_paths = [
        path
        for path in Path("src/margin").rglob("*.py")
        if "__pycache__" not in path.parts
    ]
    langchain_refs = {
        str(path)
        for path in source_paths
        if "langchain" in path.read_text(encoding="utf-8", errors="ignore").lower()
    }

    assert langchain_refs == set()


def test_langgraph_adapter_stays_inside_l3_tool_boundary() -> None:
    """Keep LangGraph-facing tool execution behind the ToolGateway boundary."""
    source = Path("src/margin/agents/tools/langgraph_adapter.py").read_text(
        encoding="utf-8"
    )

    assert "ToolGateway" in source
    assert "ToolCallRequest" in source
