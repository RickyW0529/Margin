"""Context ToolGateway handler skeletons."""

from __future__ import annotations

from margin.agents.tools.specs import ToolCallRequest


def safe_read_artifact(request: ToolCallRequest) -> dict:
    """Safe read artifact.

    Args:
        request: ToolCallRequest: .

    Returns:
        dict: .
    """
    return {"artifact_ref": request.input_json.get("artifact_ref"), "status": "stub"}
