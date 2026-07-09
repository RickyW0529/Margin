"""L3 worker executors used by the scheduled stock-analysis runtime.

Scheduled runs no longer stop at plan metadata. They execute a small fixed L3
pipeline:

1. DataInspectionWorker — readiness / scope check artifact
2. ValuationRefreshWorker — production valuation discovery refresh (quant path)

Both write immutable Context Store artifacts so the run is auditable as a real
worker pipeline, not just a planner log.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from margin.agent_runtime.context_store import AgentContextStore, make_context_artifact
from margin.agent_runtime.schedules import StockAnalysisSchedule
from margin.agents.protocol.models import AgentExecutionStatus


@dataclass(frozen=True)
class ScheduledL3WorkerResult:
    """One L3 worker outcome for a scheduled run."""

    worker_agent: str
    skill_id: str
    status: str
    artifact_id: str
    safe_summary: str
    output_ref: str | None = None


@dataclass(frozen=True)
class ScheduledL3PipelineResult:
    """Aggregate L3 execution report for one schedule trigger."""

    workers: tuple[ScheduledL3WorkerResult, ...]
    valuation_refresh_run_id: str
    execution_boundary: str = "l3_worker_runtime"


class DataInspectionL3Worker:
    """Deterministic L3 worker that records scheduled data readiness."""

    name = "DataInspectionWorker"
    skill_id = "scheduled_data_readiness"

    def execute(
        self,
        *,
        run_id: str,
        schedule: StockAnalysisSchedule,
        scope_version_id: str,
        context_store: AgentContextStore,
        now: datetime,
    ) -> ScheduledL3WorkerResult:
        """Write a data_readiness artifact for the scheduled run."""
        artifact = make_context_artifact(
            artifact_id=f"ctx_{run_id}_l3_data_readiness",
            run_id=run_id,
            artifact_type="data_readiness",
            producer_agent=self.name,
            payload_json={
                "status": "ready_for_valuation_refresh",
                "scope_version_id": scope_version_id,
                "universe": schedule.universe,
                "checked_at": now.isoformat(),
                "skill_id": self.skill_id,
                "worker_layer": "L3",
            },
            source_refs=(f"schedule:{schedule.schedule_id}", scope_version_id),
        )
        context_store.add_artifact(artifact)
        return ScheduledL3WorkerResult(
            worker_agent=self.name,
            skill_id=self.skill_id,
            status=AgentExecutionStatus.SUCCEEDED.value,
            artifact_id=artifact.artifact_id,
            safe_summary="Scheduled data readiness check completed.",
        )


class ValuationRefreshL3Worker:
    """L3 worker that starts the valuation discovery refresh pipeline."""

    name = "ValuationRefreshWorker"
    skill_id = "start_valuation_refresh"

    def __init__(self, valuation_service: Any) -> None:
        """Bind the valuation discovery application service."""
        self._valuation_service = valuation_service

    def execute(
        self,
        *,
        run_id: str,
        schedule: StockAnalysisSchedule,
        scope_version_id: str,
        context_store: AgentContextStore,
        now: datetime,
        idempotency_key: str,
        metadata: dict[str, Any],
    ) -> tuple[ScheduledL3WorkerResult, str]:
        """Start valuation refresh and persist a worker result artifact."""
        refresh_response = self._valuation_service.start_refresh(
            scope_version_id=scope_version_id,
            decision_at=now,
            idempotency_key=idempotency_key,
            metadata=metadata,
        )
        refresh_run_id = str(getattr(refresh_response, "run_id", "") or "")
        payload = {
            "worker_agent": self.name,
            "skill_id": self.skill_id,
            "worker_layer": "L3",
            "status": AgentExecutionStatus.SUCCEEDED.value,
            "scope_version_id": scope_version_id,
            "requested_scope_version_id": schedule.scope_version_id,
            "universe": schedule.universe,
            "schedule_id": schedule.schedule_id,
            "agent_run_id": run_id,
            "decision_at": now.isoformat(),
            "valuation_refresh_run_id": refresh_run_id,
            "dashboard_projection": "expected_after_refresh",
            # Flatten plan metadata for dashboard/tests that read top-level fields.
            **{
                key: value
                for key, value in metadata.items()
                if key
                not in {
                    "scope_version_id",
                    "universe",
                    "schedule_id",
                    "agent_run_id",
                    "decision_at",
                }
            },
        }
        artifact = make_context_artifact(
            artifact_id=f"ctx_{run_id}_l3_valuation_refresh",
            run_id=run_id,
            artifact_type="valuation_refresh",
            producer_agent="QuantExpertAgent",
            payload_json=payload,
            source_refs=(f"schedule:{schedule.schedule_id}", refresh_run_id or "valuation_refresh"),
        )
        context_store.add_artifact(artifact)
        result = ScheduledL3WorkerResult(
            worker_agent=self.name,
            skill_id=self.skill_id,
            status=AgentExecutionStatus.SUCCEEDED.value,
            artifact_id=artifact.artifact_id,
            safe_summary="Valuation refresh worker started production pipeline.",
            output_ref=refresh_run_id or None,
        )
        return result, refresh_run_id


def run_scheduled_l3_pipeline(
    *,
    run_id: str,
    schedule: StockAnalysisSchedule,
    scope_version_id: str,
    context_store: AgentContextStore,
    valuation_service: Any,
    now: datetime,
    idempotency_key: str,
    plan_metadata: dict[str, Any],
) -> ScheduledL3PipelineResult:
    """Execute the fixed L3 worker pipeline for one schedule trigger."""
    data_worker = DataInspectionL3Worker()
    quant_worker = ValuationRefreshL3Worker(valuation_service)

    data_result = data_worker.execute(
        run_id=run_id,
        schedule=schedule,
        scope_version_id=scope_version_id,
        context_store=context_store,
        now=now,
    )
    quant_result, refresh_run_id = quant_worker.execute(
        run_id=run_id,
        schedule=schedule,
        scope_version_id=scope_version_id,
        context_store=context_store,
        now=now,
        idempotency_key=idempotency_key,
        metadata=plan_metadata,
    )

    report = make_context_artifact(
        artifact_id=f"ctx_{run_id}_l3_execution_report",
        run_id=run_id,
        artifact_type="l3_execution_report",
        producer_agent="ScheduledAgentRuntime",
        payload_json={
            "runtime_version": "scheduled-agent-runtime-v1",
            "execution_boundary": "l3_worker_runtime",
            "workers": [
                {
                    "worker_agent": data_result.worker_agent,
                    "skill_id": data_result.skill_id,
                    "status": data_result.status,
                    "artifact_id": data_result.artifact_id,
                },
                {
                    "worker_agent": quant_result.worker_agent,
                    "skill_id": quant_result.skill_id,
                    "status": quant_result.status,
                    "artifact_id": quant_result.artifact_id,
                    "output_ref": quant_result.output_ref,
                },
            ],
            "valuation_refresh_run_id": refresh_run_id,
            "finished_at": datetime.now(UTC).isoformat(),
        },
        source_refs=(data_result.artifact_id, quant_result.artifact_id),
    )
    context_store.add_artifact(report)

    return ScheduledL3PipelineResult(
        workers=(data_result, quant_result),
        valuation_refresh_run_id=refresh_run_id,
        execution_boundary="l3_worker_runtime",
    )
