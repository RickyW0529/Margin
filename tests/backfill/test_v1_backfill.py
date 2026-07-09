"""Acceptance tests for the v1 deterministic 20-year backfill control plane."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest

from margin.agent_runtime.context_store import stable_json_hash
from margin.agents.domains.backfill_expert import BackfillExpertAgent
from margin.agents.protocol.models import AgentExecutionStatus, WorkerTaskRequest
from margin.agents.security.capability import CapabilityToken
from margin.agents.security.policies import (
    DataAccessPolicy,
    ProductionWritePolicy,
    ToolPolicy,
)
from margin.agents.tools.backfill_tools import plan_twenty_year_backfill
from margin.agents.tools.specs import ToolCallRequest
from margin.agents.workers.backfill_executor_worker import BackfillExecutorWorker
from margin.agents.workers.backfill_planner_worker import BackfillPlannerWorker
from margin.agents.workers.backfill_verifier_worker import BackfillVerifierWorker
from margin.cli.backfill import run_command
from margin.data.backfill.campaign import BackfillCampaignService
from margin.data.backfill.executor import DryRunBackfillExecutor
from margin.data.backfill.planner import BackfillPlanner
from margin.data.backfill.publisher import BackfillPublisher
from margin.data.backfill.quality import BackfillQualityService


def _capability_token() -> CapabilityToken:
    """_capability_token implementation.

    Returns:
        CapabilityToken: .
    """
    return CapabilityToken(
        token_id="cap_backfill",
        run_id="run-backfill",
        issued_by="BackfillExpertAgent",
        issued_to="BackfillPlannerWorker",
        domain="backfill",
        data_access=(DataAccessPolicy.READ_PROVIDER_STATUS,),
        production_write=(ProductionWritePolicy.WRITE_BACKFILL_STATE,),
        tool_policy=(ToolPolicy.DATA_SYNC_TOOLS,),
        allowed_artifact_types=("backfill_endpoint_plan",),
        allowed_tool_names=("data.plan_twenty_year_backfill",),
        expires_at=datetime(2026, 7, 9, tzinfo=UTC),
        max_tool_calls=4,
        max_result_bytes=8192,
    )


def test_backfill_start_date_20060101() -> None:
    """test_backfill_start_date_20060101 implementation.

    Returns:
        None: .
    """
    service = BackfillCampaignService(today=date(2026, 7, 8))

    campaign = service.init_campaign(
        campaign_name="full_market_20y",
        providers=("tushare", "akshare"),
        end_date="auto",
    )

    assert campaign.start_date == date(2006, 1, 1)
    assert campaign.start_date != date(2006, 7, 8)
    assert campaign.end_date == date(2026, 7, 7)
    assert campaign.campaign_id == "bf_full_market_20y_20260708"


def test_backfill_campaign_generates_partitions() -> None:
    """test_backfill_campaign_generates_partitions implementation.

    Returns:
        None: .
    """
    planner = BackfillPlanner()
    campaign = BackfillCampaignService(today=date(2026, 7, 8)).init_campaign(
        campaign_name="smoke",
        providers=("tushare", "akshare"),
        end_date=date(2006, 3, 31),
    )

    endpoint_plan = planner.plan_endpoints(campaign)
    partitions = planner.plan_partitions(campaign, endpoint_plan)

    endpoint_names = {endpoint.qualified_name for endpoint in endpoint_plan.endpoints}
    assert "tushare.daily" in endpoint_names
    assert "tushare.income" in endpoint_names
    assert "akshare.stock_zh_a_hist" in endpoint_names
    assert "exchange.filings" in endpoint_names
    assert "public.news" in endpoint_names
    assert len(partitions) > len(endpoint_plan.endpoints)
    assert all(partition.params_hash for partition in partitions)


def test_backfill_partition_idempotent() -> None:
    """test_backfill_partition_idempotent implementation.

    Returns:
        None: .
    """
    planner = BackfillPlanner()
    campaign = BackfillCampaignService(today=date(2026, 7, 8)).init_campaign(
        campaign_name="idempotent",
        providers=("tushare",),
        end_date=date(2006, 2, 28),
    )

    first = planner.plan_partitions(campaign, planner.plan_endpoints(campaign))
    second = planner.plan_partitions(campaign, planner.plan_endpoints(campaign))

    assert [partition.partition_id for partition in first] == [
        partition.partition_id for partition in second
    ]
    assert len({partition.params_hash for partition in first}) == len(first)


def test_provider_token_not_in_tool_output() -> None:
    """test_provider_token_not_in_tool_output implementation.

    Returns:
        None: .
    """
    request = ToolCallRequest(
        tool_call_id="tc-backfill-plan",
        run_id="run-backfill",
        task_id="task-backfill",
        caller_agent="BackfillPlannerWorker",
        tool_name="data.plan_twenty_year_backfill",
        tool_version="v1",
        input_json={
            "campaign_name": "full_market_20y",
            "provider_token": "secret-token-must-not-leak",
            "providers": ["tushare", "akshare"],
        },
        capability_token=_capability_token(),
        idempotency_key="idem-backfill-plan",
        deadline_ms=1000,
    )

    output = plan_twenty_year_backfill(request)

    assert "secret-token-must-not-leak" not in json.dumps(
        output,
        ensure_ascii=False,
        sort_keys=True,
    )
    assert output["artifact_type"] == "backfill_endpoint_plan"
    assert output["start_date"] == "2006-01-01"


def test_raw_snapshot_metadata_required() -> None:
    """test_raw_snapshot_metadata_required implementation.

    Returns:
        None: .
    """
    service = BackfillCampaignService(today=date(2026, 7, 8))
    planner = BackfillPlanner()
    executor = DryRunBackfillExecutor(
        fetched_at=datetime(2026, 7, 8, 12, tzinfo=UTC),
    )
    campaign = service.init_campaign(
        campaign_name="dry_run",
        providers=("tushare",),
        end_date=date(2006, 1, 31),
    )
    partitions = planner.plan_partitions(campaign, planner.plan_endpoints(campaign))

    result = executor.run_partition(partitions[0])

    assert result.raw_snapshot.raw_snapshot_id.startswith("raw_")
    assert result.raw_snapshot.fetched_at is not None
    assert result.raw_snapshot.available_at is not None
    assert result.raw_snapshot.row_count >= 0
    assert result.raw_snapshot.payload_hash == stable_json_hash(
        result.raw_snapshot.payload_fingerprint
    )


def test_quality_report_blocks_publish_on_schema_drift() -> None:
    """test_quality_report_blocks_publish_on_schema_drift implementation.

    Returns:
        None: .
    """
    service = BackfillCampaignService(today=date(2026, 7, 8))
    quality = BackfillQualityService()
    publisher = BackfillPublisher()
    campaign = service.init_campaign(
        campaign_name="schema_drift",
        providers=("tushare",),
        end_date=date(2006, 1, 31),
    )

    report = quality.build_report(
        campaign=campaign,
        endpoint_results=[
            {
                "provider_name": "tushare",
                "endpoint_name": "daily",
                "expected_partitions": 1,
                "completed_partitions": 1,
                "schema_drift": True,
            }
        ],
    )

    assert report.publish_allowed is False
    with pytest.raises(ValueError, match="quality report did not pass"):
        publisher.publish(campaign, report)


def test_pit_promotion_no_future_financials() -> None:
    """test_pit_promotion_no_future_financials implementation.

    Returns:
        None: .
    """
    quality = BackfillQualityService()

    result = quality.validate_pit_visibility(
        rows=[
            {
                "fact_type": "financial",
                "security_id": "000001.SZ",
                "decision_at": datetime(2020, 4, 30, tzinfo=UTC),
                "published_at": datetime(2020, 5, 1, tzinfo=UTC),
                "available_at": datetime(2020, 5, 1, 8, tzinfo=UTC),
            }
        ]
    )

    assert result.future_financial_fact_count == 1
    assert result.passed is False


def test_backfill_resume_after_partial_failure() -> None:
    """test_backfill_resume_after_partial_failure implementation.

    Returns:
        None: .
    """
    planner = BackfillPlanner()
    campaign = BackfillCampaignService(today=date(2026, 7, 8)).init_campaign(
        campaign_name="resume",
        providers=("tushare",),
        end_date=date(2006, 1, 31),
    )
    partitions = planner.plan_partitions(campaign, planner.plan_endpoints(campaign))
    failed = partitions[0].model_copy(
        update={"status": "failed", "retryable": True, "attempt_count": 1}
    )
    succeeded = partitions[1].model_copy(update={"status": "succeeded"})

    resumable = planner.resume_after_failure((failed, succeeded, *partitions[2:]))

    assert [partition.partition_id for partition in resumable] == [failed.partition_id]
    assert resumable[0].attempt_count == 1


def test_publish_requires_quality_passed_and_builds_pit_kimball_mart() -> None:
    """test_publish_requires_quality_passed_and_builds_pit_kimball_mart implementation.

    Returns:
        None: .
    """
    service = BackfillCampaignService(today=date(2026, 7, 8))
    quality = BackfillQualityService()
    publisher = BackfillPublisher()
    campaign = service.init_campaign(
        campaign_name="publish",
        providers=("tushare",),
        end_date=date(2006, 1, 31),
    )
    report = quality.build_report(
        campaign=campaign,
        endpoint_results=[
            {
                "provider_name": "tushare",
                "endpoint_name": "daily",
                "expected_partitions": 1,
                "completed_partitions": 1,
                "schema_drift": False,
            }
        ],
    )

    result = publisher.publish(campaign, report)

    assert result.status == "published"
    assert result.built_layers == ("ods", "vault", "pit", "kimball", "mart")


def test_cli_init_generates_campaign_summary() -> None:
    """test_cli_init_generates_campaign_summary implementation.

    Returns:
        None: .
    """
    output = run_command(
        [
            "init",
            "--campaign-name",
            "full_market_20y",
            "--providers",
            "tushare,akshare",
            "--start-date",
            "2006-01-01",
            "--end-date",
            "2006-01-31",
            "--today",
            "2026-07-08",
        ]
    )

    assert output["campaign"]["campaign_id"] == "bf_full_market_20y_20260708"
    assert output["campaign"]["start_date"] == "2006-01-01"
    assert output["endpoint_count"] > 0
    assert output["partition_count"] > 0


def test_backfill_expert_and_workers_emit_required_artifacts() -> None:
    """test_backfill_expert_and_workers_emit_required_artifacts implementation.

    Returns:
        None: .
    """
    expert = BackfillExpertAgent()
    worker_tasks = expert.create_worker_tasks(
        run_id="run-backfill",
        domain_task_id="dt-backfill",
        context_pack_ref="ctx-backfill",
        capability_token_ref="cap-backfill",
    )
    assert [task.worker_agent for task in worker_tasks] == [
        "BackfillPlannerWorker",
        "BackfillExecutorWorker",
        "BackfillVerifierWorker",
    ]

    planner_result = BackfillPlannerWorker()(_worker_request("BackfillPlannerWorker"))
    executor_result = BackfillExecutorWorker()(_worker_request("BackfillExecutorWorker"))
    verifier_result = BackfillVerifierWorker()(_worker_request("BackfillVerifierWorker"))

    assert planner_result.status is AgentExecutionStatus.SUCCEEDED
    assert planner_result.output_artifact_refs[0].startswith("artifact:backfill_endpoint_plan")
    assert executor_result.status is AgentExecutionStatus.SUCCEEDED
    assert executor_result.output_artifact_refs[0].startswith("artifact:backfill_partition_result")
    assert verifier_result.status is AgentExecutionStatus.SUCCEEDED
    assert verifier_result.output_artifact_refs[0].startswith("artifact:backfill_quality_report")


def _worker_request(worker_agent: str) -> WorkerTaskRequest:
    """Execute _worker_request logic.

    Args:
        worker_agent: str: .

    Returns:
        WorkerTaskRequest: .
    """
    return WorkerTaskRequest(
        run_id="run-backfill",
        domain_task_id="dt-backfill",
        worker_task_id=f"wt-{worker_agent}",
        parent_agent="BackfillExpertAgent",
        worker_agent=worker_agent,
        skill_id="twenty_year_backfill",
        task_goal="Create deterministic 20-year backfill artifact.",
        input_context_pack_ref="ctx-backfill",
        required_output_types=("backfill_artifact",),
        tool_policy_ref="policy-backfill",
        capability_token_ref="cap-backfill",
        token_budget=1024,
        max_tool_calls=2,
        deadline_ms=1000,
        idempotency_key=f"idem-{worker_agent}",
    )
