"""Backfill planner worker executor."""

from __future__ import annotations

from datetime import date

from margin.agents.protocol.models import (
    AgentExecutionStatus,
    WorkerTaskRequest,
    WorkerTaskResult,
)
from margin.core.hashing import stable_json_hash
from margin.data.backfill.campaign import BackfillCampaignService
from margin.data.backfill.planner import BackfillPlanner


class BackfillPlannerWorker:
    """BackfillPlannerWorker.."""

    name = "BackfillPlannerWorker"
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
        )
        planner = BackfillPlanner()
        endpoint_plan = planner.plan_endpoints(campaign)
        partitions = planner.plan_partitions(campaign, endpoint_plan)
        payload_hash = stable_json_hash(
            {
                "campaign_id": campaign.campaign_id,
                "endpoint_plan_hash": endpoint_plan.payload_hash,
                "partition_count": len(partitions),
            }
        )
        return WorkerTaskResult(
            run_id=request.run_id,
            domain_task_id=request.domain_task_id,
            worker_task_id=request.worker_task_id,
            worker_agent=self.name,
            skill_id=request.skill_id,
            status=AgentExecutionStatus.SUCCEEDED,
            output_artifact_refs=(f"artifact:backfill_endpoint_plan:{payload_hash}",),
            audit_event_refs=(f"audit:{request.worker_task_id}:planned",),
            safe_summary="Deterministic 20-year endpoint and partition plan created.",
        )
