"""Backfill executor worker."""

from __future__ import annotations

from datetime import date

from margin.agent_runtime.context_store import stable_json_hash
from margin.agents.protocol.models import (
    AgentExecutionStatus,
    WorkerTaskRequest,
    WorkerTaskResult,
)
from margin.data.backfill.campaign import BackfillCampaignService
from margin.data.backfill.executor import DryRunBackfillExecutor
from margin.data.backfill.planner import BackfillPlanner


class BackfillExecutorWorker:
    """BackfillExecutorWorker.."""

    name = "BackfillExecutorWorker"
    skill_id = "twenty_year_backfill"

    def __call__(self, request: WorkerTaskRequest) -> WorkerTaskResult:
        """Call .

        Args:
            request: WorkerTaskRequest: .

        Returns:
            WorkerTaskResult: .
        """
        service = BackfillCampaignService(today=date(2026, 7, 8))
        campaign = service.init_campaign(
            campaign_name="full_market_20y",
            providers=("tushare", "akshare"),
            end_date=date(2006, 1, 31),
        )
        planner = BackfillPlanner()
        partitions = planner.plan_partitions(campaign, planner.plan_endpoints(campaign))
        result = DryRunBackfillExecutor().run_partition(partitions[0])
        payload_hash = stable_json_hash(result.model_dump(mode="json"))
        return WorkerTaskResult(
            run_id=request.run_id,
            domain_task_id=request.domain_task_id,
            worker_task_id=request.worker_task_id,
            worker_agent=self.name,
            skill_id=request.skill_id,
            status=AgentExecutionStatus.SUCCEEDED,
            output_artifact_refs=(f"artifact:backfill_partition_result:{payload_hash}",),
            audit_event_refs=(f"audit:{request.worker_task_id}:executed",),
            safe_summary="Dry-run backfill partition metadata generated.",
        )
