"""Quant ToolGateway handler skeletons."""

from __future__ import annotations

from margin.agents.tools.specs import ToolCallRequest


def run_screen(request: ToolCallRequest) -> dict:
    """Run screen.

    Args:
        request: ToolCallRequest: .

    Returns:
        dict: .
    """
    return {"as_of_date": request.input_json.get("as_of_date"), "candidates": []}
