"""Default v1 Agent cards and v0 AgentCard adapters."""

from __future__ import annotations

from collections.abc import Iterable

from margin.agent_runtime.models import AgentCard, AgentPermissionMode
from margin.agents.cards.domain_cards import DomainAgentCard
from margin.agents.cards.worker_cards import WorkerAgentCard, WorkerSkill
from margin.agents.security.policies import (
    DataAccessPolicy,
    ProductionWritePolicy,
    ToolPolicy,
)

_DOMAIN_BY_AGENT = {
    "DataInspectionAgent": "data",
    "QuantAgent": "quant",
    "PerformanceGrowthScoutAgent": "stock_research",
    "RagCoverageGateAgent": "evidence",
    "FundamentalAnalystAgent": "stock_research",
    "SentimentMonitorAgent": "news",
    "FusionResearchAgent": "stock_research",
    "StockAnalystAgent": "stock_research",
    "GeneralQnaAgent": "general",
    "DataAnalystAgent": "general",
    "CodeSandboxAgent": "code",
}


def v0_agent_card_to_worker_card(card: AgentCard) -> WorkerAgentCard:
    """Convert an existing v0 AgentCard into a v1 WorkerAgentCard.

    Args:
        card: AgentCard: .

    Returns:
        WorkerAgentCard: .
    """
    domain = _DOMAIN_BY_AGENT.get(card.name, "general")
    write_policies = tuple(_write_policy(skill.write_policy) for skill in card.skills)
    return WorkerAgentCard(
        name=card.name,
        version=card.version,
        domain=domain,
        description=card.description,
        skills=tuple(
            WorkerSkill(
                skill_id=skill.skill_id,
                description=skill.description,
                input_artifact_types=skill.required_context_artifacts,
                output_artifact_types=skill.produced_context_artifacts,
                deterministic="deterministic" in skill.tags,
            )
            for skill in card.skills
        ),
        supported_runtimes=("deterministic",),
        data_access_policy=_data_access_policy(domain),
        production_write_policy=tuple(dict.fromkeys(write_policies)),
        tool_policy=_tool_policy(domain),
        max_context_tokens=8192 if domain in {"evidence", "stock_research"} else 4096,
        max_tool_calls=0 if domain in {"general", "quant", "data"} else 4,
        requires_human_confirmation=False,
    )


def v0_agent_cards_to_worker_cards(cards: Iterable[AgentCard]) -> tuple[WorkerAgentCard, ...]:
    """Convert v0 AgentCards into v1 WorkerAgentCards.

    Args:
        cards: Iterable[AgentCard]: .

    Returns:
        tuple[WorkerAgentCard, ...]: .
    """
    return tuple(v0_agent_card_to_worker_card(card) for card in cards)


def default_domain_agent_cards() -> tuple[DomainAgentCard, ...]:
    """Return the default Layer-2 Domain ExpertAgent cards.

    Returns:
        tuple[DomainAgentCard, ...]: .
    """
    return (
        DomainAgentCard(
            name="DataExpertAgent",
            version="v1.0",
            domain="data",
            description="Plans data freshness, quality, provider, and PIT checks.",
            worker_agent_names=("DataInspectionAgent",),
            required_output_types=("data_context_capsule", "data_readiness"),
            data_access_policy=(DataAccessPolicy.READ_PROVIDER_STATUS,),
            production_write_policy=(ProductionWritePolicy.WRITE_CONTEXT_ONLY,),
            tool_policy=(ToolPolicy.DATA_SYNC_TOOLS,),
        ),
        DomainAgentCard(
            name="QuantExpertAgent",
            version="v1.0",
            domain="quant",
            description="Plans PIT feature build, quant screening, and quant audit.",
            worker_agent_names=("QuantAgent",),
            required_output_types=("quant_context_capsule", "quant_result"),
            data_access_policy=(DataAccessPolicy.READ_ANALYSIS_MART,),
            production_write_policy=(ProductionWritePolicy.WRITE_CONTEXT_ONLY,),
            tool_policy=(ToolPolicy.QUANT_TOOLS,),
        ),
        DomainAgentCard(
            name="EvidenceRagExpertAgent",
            version="v1.0",
            domain="evidence",
            description="Plans RAG coverage, retrieval, evidence package, and citation checks.",
            worker_agent_names=("RagCoverageGateAgent",),
            required_output_types=("evidence_context_capsule", "evidence_package"),
            data_access_policy=(
                DataAccessPolicy.READ_EVIDENCE,
                DataAccessPolicy.READ_VECTOR_INDEX,
            ),
            production_write_policy=(ProductionWritePolicy.WRITE_CONTEXT_ONLY,),
            tool_policy=(ToolPolicy.RETRIEVAL_TOOLS,),
        ),
        DomainAgentCard(
            name="StockResearchExpertAgent",
            version="v1.0",
            domain="stock_research",
            description="Plans fundamental, risk, counter-argument, and synthesis work.",
            worker_agent_names=(
                "PerformanceGrowthScoutAgent",
                "FundamentalAnalystAgent",
                "FusionResearchAgent",
                "StockAnalystAgent",
            ),
            required_output_types=("stock_research_context_capsule",),
            data_access_policy=(
                DataAccessPolicy.READ_ANALYSIS_MART,
                DataAccessPolicy.READ_EVIDENCE,
            ),
            production_write_policy=(ProductionWritePolicy.WRITE_CONTEXT_ONLY,),
            tool_policy=(ToolPolicy.READ_ONLY_TOOLS,),
        ),
        DomainAgentCard(
            name="GeneralQnaExpertAgent",
            version="v1.0",
            domain="general",
            description="Plans ordinary Q&A and product-usage responses.",
            worker_agent_names=("GeneralQnaAgent", "DataAnalystAgent"),
            required_output_types=("explanation",),
            data_access_policy=(
                DataAccessPolicy.READ_CHAT_SUMMARY,
                DataAccessPolicy.READ_DASHBOARD,
            ),
            production_write_policy=(ProductionWritePolicy.WRITE_CONTEXT_ONLY,),
            tool_policy=(ToolPolicy.READ_ONLY_TOOLS,),
        ),
        DomainAgentCard(
            name="CodeExecutionExpertAgent",
            version="v1.0",
            domain="code",
            description="Plans sandboxed read-only computation when explicitly enabled.",
            worker_agent_names=("CodeSandboxAgent",),
            required_output_types=("analysis_table", "chart_spec", "computed_metric"),
            data_access_policy=(DataAccessPolicy.READ_DASHBOARD,),
            production_write_policy=(ProductionWritePolicy.WRITE_CONTEXT_ONLY,),
            tool_policy=(ToolPolicy.SANDBOX_TOOLS,),
        ),
    )


def _write_policy(mode: AgentPermissionMode) -> ProductionWritePolicy:
    """Process _write_policy.

    Args:
        mode: AgentPermissionMode: .

    Returns:
        ProductionWritePolicy: .
    """
    if mode is AgentPermissionMode.WRITE_ALLOWED:
        return ProductionWritePolicy.WRITE_CONTEXT_ONLY
    return ProductionWritePolicy.NONE


def _data_access_policy(domain: str) -> tuple[DataAccessPolicy, ...]:
    """Process _data_access_policy.

    Args:
        domain: str: .

    Returns:
        tuple[DataAccessPolicy, ...]: .
    """
    if domain == "general":
        return (DataAccessPolicy.READ_CHAT_SUMMARY, DataAccessPolicy.READ_DASHBOARD)
    if domain == "quant":
        return (DataAccessPolicy.READ_ANALYSIS_MART,)
    if domain == "evidence":
        return (DataAccessPolicy.READ_EVIDENCE, DataAccessPolicy.READ_VECTOR_INDEX)
    if domain == "data":
        return (DataAccessPolicy.READ_PROVIDER_STATUS,)
    return (DataAccessPolicy.READ_ANALYSIS_MART, DataAccessPolicy.READ_EVIDENCE)


def _tool_policy(domain: str) -> tuple[ToolPolicy, ...]:
    """Process _tool_policy.

    Args:
        domain: str: .

    Returns:
        tuple[ToolPolicy, ...]: .
    """
    if domain == "quant":
        return (ToolPolicy.QUANT_TOOLS,)
    if domain == "evidence":
        return (ToolPolicy.RETRIEVAL_TOOLS,)
    if domain == "data":
        return (ToolPolicy.DATA_SYNC_TOOLS,)
    if domain == "code":
        return (ToolPolicy.SANDBOX_TOOLS,)
    return (ToolPolicy.READ_ONLY_TOOLS,)
