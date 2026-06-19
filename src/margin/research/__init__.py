"""Multi-agent research module."""

from margin.research.agents import Agent, AgentContext, AgentOutput
from margin.research.llm import DeterministicLLMProvider, LLMProvider, ModelRouter, TaskType
from margin.research.models import (
    ResearchSignal,
    ResearchSnapshot,
    SignalType,
    VersionRef,
    WorkflowState,
)
from margin.research.repository import (
    MemoryResearchRepository,
    ResearchRepository,
    SQLAlchemyResearchRepository,
)
from margin.research.service import ResearchService
from margin.research.snapshot import ResearchSnapshotBuilder
from margin.research.tools import ToolPermission, ToolRegistry
from margin.research.workflow import ResearchWorkflow, WorkflowResult

__all__ = [
    "Agent",
    "AgentContext",
    "AgentOutput",
    "DeterministicLLMProvider",
    "LLMProvider",
    "MemoryResearchRepository",
    "ModelRouter",
    "ResearchService",
    "ResearchSignal",
    "ResearchSnapshot",
    "ResearchSnapshotBuilder",
    "ResearchRepository",
    "ResearchWorkflow",
    "SQLAlchemyResearchRepository",
    "SignalType",
    "TaskType",
    "ToolPermission",
    "ToolRegistry",
    "VersionRef",
    "WorkflowResult",
    "WorkflowState",
]
