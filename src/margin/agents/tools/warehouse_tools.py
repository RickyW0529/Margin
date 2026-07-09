"""Warehouse ToolGateway handler skeletons."""

from __future__ import annotations

from margin.agents.tools.specs import ToolCallRequest


def query_data_freshness(request: ToolCallRequest) -> dict:
    """Query data freshness.

    Args:
        request: ToolCallRequest: .

    Returns:
        dict: .
    """
    return {"dataset": request.input_json.get("dataset", "unknown"), "status": "unknown"}
