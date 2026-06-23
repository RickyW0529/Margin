"""Minimal tool manifests supplied to LLM node prompts."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from margin.research.tools.definitions import ToolCapability


class ToolManifestEntry(BaseModel):
    """One tool visible to a specific graph node."""

    name: str
    capability: ToolCapability
    version: str
    description: str
    input_schema: dict[str, Any]

    model_config = {"frozen": True}


class ToolManifest(BaseModel):
    """Versioned node-scoped manifest."""

    graph_run_id: str
    node_name: str
    security_id: str
    decision_at: str
    policy_version: str
    tools: tuple[ToolManifestEntry, ...]
    max_calls: int
    max_result_bytes: int

    model_config = {"frozen": True}
