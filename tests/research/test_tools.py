"""Tests for the research tool system."""

from __future__ import annotations

from margin.research.tools import PythonTool, RetrievalTool, ToolRegistry


def test_registry_registers_and_calls_python_tool():
    registry = ToolRegistry()
    registry.register(PythonTool())
    result = registry.call("python", {"expression": "1 + 1"})
    assert result.success is True
    assert result.data == 2


def test_python_tool_disallows_unsafe_names():
    tool = PythonTool()
    result = tool.run({"expression": "__import__('os').system('ls')"})
    assert result.success is False
    assert "disallowed" in result.error


def test_retrieval_tool_requires_symbol_and_decision_at():
    tool = RetrievalTool(pipeline=None)
    result = tool.run({"query": "cash flow"})
    assert result.success is False
    assert "symbol" in result.error.lower()


def test_registry_defaults_register_all_tools():
    registry = ToolRegistry()
    registry.register_defaults()
    names = registry.list_tools()
    assert "python" in names
    assert "retrieval" in names
    assert "market_data" in names
    assert "valuation" in names


def test_tool_call_record_exists_for_audit():
    from margin.research.tools import ToolCallRecord

    record = ToolCallRecord(tool_name="python", params={"expression": "1+1"}, success=True)
    assert record.tool_name == "python"
    assert record.call_id.startswith("tc_")
