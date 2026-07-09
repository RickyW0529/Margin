"""RAG ToolGateway handler skeletons."""

from __future__ import annotations

from margin.agents.tools.specs import ToolCallRequest


def retrieve_evidence(request: ToolCallRequest) -> dict:
    """Retrieve evidence.

    Args:
        request: ToolCallRequest: .

    Returns:
        dict: .
    """
    return {"subject": request.input_json.get("subject"), "evidence_refs": []}
