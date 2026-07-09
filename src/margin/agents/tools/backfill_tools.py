"""Backfill ToolGateway handlers.

These handlers expose deterministic control-plane operations only. They do not
call live providers or return secrets/raw payloads.
"""

from __future__ import annotations

from datetime import date

from margin.agents.tools.specs import ToolCallRequest
from margin.data.backfill.campaign import BackfillCampaignService
from margin.data.backfill.planner import BackfillPlanner


def plan_twenty_year_backfill(request: ToolCallRequest) -> dict:
    """Plan twenty year backfill.

    Args:
        request: ToolCallRequest: .

    Returns:
        dict: .
    """
    campaign_name = str(request.input_json.get("campaign_name", "full_market_20y"))
    providers_raw = request.input_json.get("providers", ["tushare", "akshare"])
    providers = tuple(str(provider) for provider in providers_raw)
    end_date_raw = request.input_json.get("end_date", "auto")
    end_date = date.fromisoformat(end_date_raw) if _is_iso_date(end_date_raw) else end_date_raw
    service = BackfillCampaignService()
    campaign = service.init_campaign(
        campaign_name=campaign_name,
        providers=providers,
        years=int(request.input_json.get("years", 20)),
        start_date=request.input_json.get("start_date", "2006-01-01"),
        end_date=end_date,
    )
    planner = BackfillPlanner()
    endpoint_plan = planner.plan_endpoints(campaign)
    partitions = planner.plan_partitions(campaign, endpoint_plan)
    return {
        "artifact_type": "backfill_endpoint_plan",
        "campaign_id": campaign.campaign_id,
        "start_date": campaign.start_date.isoformat(),
        "end_date": campaign.end_date.isoformat(),
        "providers": list(campaign.providers),
        "endpoint_count": len(endpoint_plan.endpoints),
        "partition_count": len(partitions),
        "sample_partitions": [partition.model_dump(mode="json") for partition in partitions[:5]],
        "payload_hash": endpoint_plan.payload_hash,
    }


def _is_iso_date(value: object) -> bool:
    """Is iso date.

    Args:
        value: object: .

    Returns:
        bool: .
    """
    if not isinstance(value, str):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True
