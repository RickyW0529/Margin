"""Fixed-flow step definition loading."""

from __future__ import annotations

import json
from importlib.resources import files

from margin.agent_runtime.models import AgentFlowDefinition


def load_scheduled_stock_analysis_flow() -> AgentFlowDefinition:
    """Load the fixed scheduled stock-analysis flow definition."""
    resource = files("margin.agent_runtime.flows").joinpath(
        "scheduled_stock_analysis_steps.json"
    )
    payload = json.loads(resource.read_text(encoding="utf-8"))
    payload.pop("$schema", None)
    flow = AgentFlowDefinition.model_validate(payload)
    return flow.model_copy(update={"steps": flow.ordered_steps()})
