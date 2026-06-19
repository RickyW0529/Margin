"""High-level research service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from margin.core.audit_repository import AuditRepository
from margin.core.models import AuditLogRecord
from margin.research.llm import LLMProvider, ModelRouter, TaskType
from margin.research.models import ResearchSnapshot
from margin.research.repository import MemoryResearchRepository, ResearchRepository
from margin.research.tools import ToolRegistry
from margin.research.workflow import ResearchWorkflow, WorkflowResult


class ResearchService:
    """Entry point for running research workflows."""

    def __init__(
        self,
        tool_registry: ToolRegistry | None = None,
        llm_provider: LLMProvider | None = None,
        strategy_config: dict[str, Any] | None = None,
        repository: ResearchRepository | None = None,
        audit_repository: AuditRepository | None = None,
    ) -> None:
        self._tools = tool_registry or ToolRegistry()
        if not self._tools.list_tools():
            self._tools.register_defaults()
        self._llm = llm_provider
        self._router: ModelRouter | None = None
        if llm_provider is not None:
            provider_name = llm_provider.descriptor.name
            routed_tasks = {
                task: provider_name
                for task in (
                    TaskType.WEBSEARCH,
                    TaskType.SUMMARY,
                    TaskType.EVIDENCE,
                    TaskType.RISK,
                    TaskType.REFLECT,
                    TaskType.SIGNAL,
                    TaskType.EXTRACTION,
                    TaskType.VALIDATION,
                )
            }
            self._router = ModelRouter(
                routed_tasks,
                llm_providers={provider_name: llm_provider},
            )
        self._strategy = strategy_config or {}
        self._repository = repository or MemoryResearchRepository()
        self._audit_repository = audit_repository

    def run(
        self,
        symbol: str,
        decision_at: datetime | None = None,
        portfolio_id: str | None = None,
    ) -> WorkflowResult:
        decision_at = decision_at or datetime.now(UTC)
        workflow = ResearchWorkflow(
            symbol=symbol,
            decision_at=decision_at,
            tool_registry=self._tools,
            llm_provider=self._llm,
            model_router=self._router,
            strategy_config=self._strategy,
            portfolio_id=portfolio_id,
            repository=self._repository,
        )
        result = workflow.run()
        if self._audit_repository is not None and result.snapshot is not None:
            snapshot = ResearchSnapshot.model_validate(result.snapshot)
            self._audit_repository.record(
                AuditLogRecord(
                    record_id=f"ar_{snapshot.snapshot_id}",
                    record_type="research_snapshot",
                    object_id=snapshot.snapshot_id,
                    trace_id=(
                        snapshot.traces[0].trace_id
                        if snapshot.traces
                        else result.run_id
                    ),
                    input_hash=snapshot.input_hash,
                    output_hash=snapshot.output_hash,
                    payload_json=snapshot.model_dump(mode="json"),
                )
            )
        return result

    def list_tools(self) -> list[dict[str, str]]:
        """Return public metadata for registered research tools."""
        return self._tools.describe_tools()

    def get_snapshot(self, snapshot_id: str) -> ResearchSnapshot | None:
        """Return a persisted terminal snapshot."""
        return self._repository.get_snapshot(snapshot_id)
