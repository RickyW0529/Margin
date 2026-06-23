"""v0.2 AI delta-review research module."""

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

__all__ = [
    "DeterministicLLMProvider",
    "LLMProvider",
    "MemoryResearchRepository",
    "ModelRouter",
    "ResearchService",
    "ResearchSignal",
    "ResearchSnapshot",
    "ResearchSnapshotBuilder",
    "ResearchRepository",
    "SQLAlchemyResearchRepository",
    "SignalType",
    "TaskType",
    "VersionRef",
    "WorkflowState",
]
