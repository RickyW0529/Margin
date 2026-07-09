"""Legacy agent runtime storage and compatibility layer.

Canonical application control plane lives in ``margin.agents`` (v1 MainRuntime /
AgentRuntimeService / workers). This package still owns:

- chat session persistence
- schedule rows
- Context Store artifact tables used by the chat UI
- quant agent strategy profile helpers
- legacy MainAgentRuntime for older tests only

Do not add new production planners or tool executors here.
"""

from margin.agent_runtime.cards import AgentCardRegistry, default_agent_card_registry
from margin.agent_runtime.expert_agents import (
    StockAnalystAdjustmentResult,
    StockAnalystAgent,
)
from margin.agent_runtime.guardrails import (
    GuardrailDecisionType,
    InputGuardrail,
    PlanGuardrail,
)
from margin.agent_runtime.main_agent import MainAgentRuntime
from margin.agent_runtime.models import (
    AgentCard,
    AgentExecutionStatus,
    AgentFlowDefinition,
    AgentPermissionMode,
    AgentRun,
    AgentRunType,
    AgentSkill,
    AgentStep,
    AgentStepDefinition,
    ContextArtifact,
    GuardrailDecision,
    GuardrailStage,
    MainAgentPlanResult,
    MainAgentReviewResult,
)
from margin.agent_runtime.quant_agent import (
    CURRENT_QUANT_AGENT_ML_PROFILE,
    QuantAgentStrategyProfile,
    current_quant_agent_strategy_profile,
)
from margin.agent_runtime.step_definitions import load_scheduled_stock_analysis_flow

__all__ = [
    "AgentCard",
    "AgentCardRegistry",
    "AgentExecutionStatus",
    "AgentFlowDefinition",
    "AgentPermissionMode",
    "AgentRun",
    "AgentRunType",
    "AgentSkill",
    "AgentStep",
    "AgentStepDefinition",
    "ContextArtifact",
    "default_agent_card_registry",
    "GuardrailDecision",
    "GuardrailDecisionType",
    "GuardrailStage",
    "InputGuardrail",
    "load_scheduled_stock_analysis_flow",
    "MainAgentPlanResult",
    "MainAgentReviewResult",
    "MainAgentRuntime",
    "PlanGuardrail",
    "CURRENT_QUANT_AGENT_ML_PROFILE",
    "QuantAgentStrategyProfile",
    "current_quant_agent_strategy_profile",
    "StockAnalystAdjustmentResult",
    "StockAnalystAgent",
]
