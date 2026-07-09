"""Compatibility adapters from legacy agent_runtime models to v1 protocol."""

from __future__ import annotations

from margin.agent_runtime.models import AgentFlowDefinition, AgentStep, ContextArtifact
from margin.agents.protocol.models import DomainTaskRequest

_STEP_TO_DOMAIN_AGENT = {
    "DataInspectionAgent": ("DataExpertAgent", "data"),
    "QuantAgent": ("QuantExpertAgent", "quant"),
    "PerformanceGrowthScoutAgent": ("StockResearchExpertAgent", "stock_research"),
    "RagCoverageGateAgent": ("EvidenceRagExpertAgent", "evidence"),
    "FundamentalAnalystAgent": ("StockResearchExpertAgent", "stock_research"),
    "SentimentMonitorAgent": ("StockResearchExpertAgent", "stock_research"),
    "FusionResearchAgent": ("StockResearchExpertAgent", "stock_research"),
    "StockAnalystAgent": ("StockResearchExpertAgent", "stock_research"),
}


def map_v0_flow_to_domain_tasks(
    flow: AgentFlowDefinition,
    *,
    run_id: str,
    context_pack_ref: str,
    capability_token_ref: str,
) -> tuple[DomainTaskRequest, ...]:
    """Map v0 flow to domain tasks.

    Args:
        flow: AgentFlowDefinition: .
        run_id: str: .
        context_pack_ref: str: .
        capability_token_ref: str: .

    Returns:
        tuple[DomainTaskRequest, ...]: .
    """
    tasks: list[DomainTaskRequest] = []
    for step in flow.ordered_steps():
        expert_agent, domain = _STEP_TO_DOMAIN_AGENT.get(
            step.expert_agent,
            ("GeneralQnaExpertAgent", "general"),
        )
        tasks.append(
            DomainTaskRequest(
                run_id=run_id,
                domain_task_id=f"dt_{step.step_id}",
                to_domain_agent=expert_agent,
                domain=domain,
                user_intent_summary=flow.description or flow.flow_id,
                task_goal=step.description or step.skill_id,
                required_output_types=step.produced_artifacts,
                input_context_pack_ref=context_pack_ref,
                input_artifact_refs=step.required_artifacts,
                capability_token_ref=capability_token_ref,
                constraints={
                    "legacy_step_id": step.step_id,
                    "legacy_expert_agent": step.expert_agent,
                },
                token_budget=6000,
                deadline_ms=60_000,
                idempotency_key=f"{run_id}:{flow.flow_id}:{step.step_id}",
            )
        )
    return tuple(tasks)


def v0_step_to_task_ref(step: AgentStep) -> str:
    """V0 step to task ref.

    Args:
        step: AgentStep: .

    Returns:
        str: .
    """
    return f"dt_{step.step_id}"


def v0_artifact_ref(artifact: ContextArtifact) -> str:
    """V0 artifact ref.

    Args:
        artifact: ContextArtifact: .

    Returns:
        str: .
    """
    return artifact.artifact_id
