"""Agent card registry loaded from versioned runtime manifests."""

from __future__ import annotations

from collections.abc import Iterable

from margin.agent_runtime.models import AgentCard, AgentPermissionMode
from margin.agents.cards.domain_cards import DomainAgentCard
from margin.agents.cards.manifest import load_agent_card_manifest
from margin.agents.cards.worker_cards import WorkerAgentCard, WorkerSkill
from margin.agents.security.policies import (
    DataAccessPolicy,
    ProductionWritePolicy,
    ToolPolicy,
)

# This mapping is used only by the frozen v0 compatibility adapter. The v2
# control plane loads all Agent relationships from manifests below.
_LEGACY_DOMAIN_BY_AGENT = {
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
    """Convert a legacy card for v0-only compatibility tests and adapters."""
    domain = _LEGACY_DOMAIN_BY_AGENT.get(card.name, "general")
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
        data_access_policy=_legacy_data_access_policy(domain),
        production_write_policy=tuple(dict.fromkeys(write_policies)),
        tool_policy=_legacy_tool_policy(domain),
        max_context_tokens=8192 if domain in {"evidence", "stock_research"} else 4096,
        max_tool_calls=0 if domain in {"general", "quant", "data"} else 4,
        requires_human_confirmation=False,
    )


def v0_agent_cards_to_worker_cards(cards: Iterable[AgentCard]) -> tuple[WorkerAgentCard, ...]:
    """Convert legacy v0 cards without exposing them to the v2 runtime."""
    return tuple(v0_agent_card_to_worker_card(card) for card in cards)


def default_domain_agent_cards(*, profile: str = "user_qna") -> tuple[DomainAgentCard, ...]:
    """Return Domain ExpertAgent cards from a packaged runtime profile."""
    return load_agent_card_manifest(profile).domain_agents


def default_worker_agent_cards(
    *,
    domain: str | None = None,
    profile: str = "user_qna",
) -> tuple[WorkerAgentCard, ...]:
    """Return WorkerAgent cards from a packaged runtime profile."""
    cards = load_agent_card_manifest(profile).worker_agents
    if domain is None:
        return cards
    return tuple(card for card in cards if card.domain == domain)


def scheduled_domain_agent_cards() -> tuple[DomainAgentCard, ...]:
    """Return the dynamic scheduled-runtime ExpertAgent profile."""
    return default_domain_agent_cards(profile="scheduled")


def scheduled_worker_agent_cards() -> tuple[WorkerAgentCard, ...]:
    """Return the dynamic scheduled-runtime WorkerAgent profile."""
    return default_worker_agent_cards(profile="scheduled")


def _write_policy(mode: AgentPermissionMode) -> ProductionWritePolicy:
    if mode is AgentPermissionMode.WRITE_ALLOWED:
        return ProductionWritePolicy.WRITE_CONTEXT_ONLY
    return ProductionWritePolicy.NONE


def _legacy_data_access_policy(domain: str) -> tuple[DataAccessPolicy, ...]:
    if domain == "general":
        return (DataAccessPolicy.READ_CHAT_SUMMARY, DataAccessPolicy.READ_DASHBOARD)
    if domain == "quant":
        return (DataAccessPolicy.READ_ANALYSIS_MART,)
    if domain == "evidence":
        return (DataAccessPolicy.READ_EVIDENCE, DataAccessPolicy.READ_VECTOR_INDEX)
    if domain == "data":
        return (DataAccessPolicy.READ_PROVIDER_STATUS,)
    if domain == "code":
        return (DataAccessPolicy.READ_WORKSPACE,)
    return (DataAccessPolicy.READ_ANALYSIS_MART, DataAccessPolicy.READ_EVIDENCE)


def _legacy_tool_policy(domain: str) -> tuple[ToolPolicy, ...]:
    if domain == "quant":
        return (ToolPolicy.QUANT_TOOLS,)
    if domain == "evidence":
        return (ToolPolicy.RETRIEVAL_TOOLS,)
    if domain == "data":
        return (ToolPolicy.DATA_SYNC_TOOLS,)
    if domain == "code":
        return (ToolPolicy.WORKSPACE_TOOLS,)
    return (ToolPolicy.READ_ONLY_TOOLS,)
