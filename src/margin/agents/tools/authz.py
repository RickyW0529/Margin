"""ToolGateway authorization checks."""

from __future__ import annotations

from margin.agents.security.capability import CapabilityToken
from margin.agents.tools.specs import ToolSpec


def capability_allows_tool(token: CapabilityToken, spec: ToolSpec) -> bool:
    """Capability allows tool.

    Args:
        token: CapabilityToken: .
        spec: ToolSpec: .

    Returns:
        bool: .
    """
    if spec.tool_name not in token.allowed_tool_names:
        return False
    if not set(spec.required_data_access).issubset(set(token.data_access)):
        return False
    if not set(spec.required_write_policy).issubset(set(token.production_write)):
        return False
    return set(spec.required_tool_policy).issubset(set(token.tool_policy))
