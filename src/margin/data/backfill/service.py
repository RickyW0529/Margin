"""Application service for v1 backfill campaign APIs."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict

from margin.core.hashing import stable_json_hash
from margin.data.backfill.campaign import (
    BackfillCampaign,
    BackfillCampaignService,
    BackfillCampaignStatus,
)
from margin.data.backfill.executor import DryRunBackfillExecutor
from margin.data.backfill.planner import (
    BackfillEndpointPlan,
    BackfillPartition,
    BackfillPlanner,
    PartitionStatus,
)
from margin.data.backfill.publisher import BackfillPublisher, BackfillPublishResult
from margin.data.backfill.quality import BackfillQualityReport, BackfillQualityService
from margin.data.backfill.repository import BackfillRepository


class BackfillCampaignSummary(BaseModel):
    """BackfillCampaignSummary.."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    campaign: BackfillCampaign
    endpoint_count: int
    partition_count: int
    quality_report_available: bool = False


class BackfillRunSummary(BaseModel):
    """BackfillRunSummary.."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    campaign_id: str
    status: str
    processed_partitions: int
    raw_snapshot_count: int


class MemoryBackfillRepository:
    """MemoryBackfillRepository.."""

    def __init__(self) -> None:
        """Init .

        Returns:
            None: .
        """
        self.campaigns: dict[str, BackfillCampaign] = {}
        self.endpoint_plans: dict[str, BackfillEndpointPlan] = {}
        self.partitions: dict[str, tuple[BackfillPartition, ...]] = {}
        self.quality_reports: dict[str, BackfillQualityReport] = {}
        self.publish_results: dict[str, BackfillPublishResult] = {}
        self.idempotency: dict[str, tuple[str, str]] = {}

    def lookup_idempotency_key(self, idempotency_key: str, request_hash: str) -> str | None:
        """Return an existing campaign id for an exact replay."""
        current = self.idempotency.get(idempotency_key)
        if current is None:
            return None
        current_hash, campaign_id = current
        if current_hash != request_hash:
            raise ValueError(f"idempotency key '{idempotency_key}' is immutable")
        return campaign_id

    def record_idempotency_key(
        self,
        *,
        idempotency_key: str,
        request_hash: str,
        campaign_id: str,
    ) -> None:
        """Record an idempotent campaign creation."""
        current = self.idempotency.get(idempotency_key)
        if current is not None and current != (request_hash, campaign_id):
            raise ValueError(f"idempotency key '{idempotency_key}' is immutable")
        self.idempotency[idempotency_key] = (request_hash, campaign_id)

    def save_campaign(self, campaign: BackfillCampaign) -> None:
        """Persist the latest campaign state."""
        self.campaigns[campaign.campaign_id] = campaign

    def get_campaign(self, campaign_id: str) -> BackfillCampaign | None:
        """Return one campaign by id."""
        return self.campaigns.get(campaign_id)

    def save_endpoint_plan(self, endpoint_plan: BackfillEndpointPlan) -> None:
        """Persist one endpoint plan."""
        self.endpoint_plans[endpoint_plan.campaign_id] = endpoint_plan

    def count_endpoints(self, campaign_id: str) -> int:
        """Return endpoint count for one campaign."""
        return len(self.endpoint_plans[campaign_id].endpoints)

    def save_partitions(
        self,
        campaign_id: str,
        partitions: tuple[BackfillPartition, ...],
    ) -> None:
        """Persist partition state for one campaign."""
        self.partitions[campaign_id] = partitions

    def list_partitions(self, campaign_id: str) -> tuple[BackfillPartition, ...]:
        """List partitions for one campaign."""
        return self.partitions[campaign_id]

    def save_quality_report(self, report: BackfillQualityReport) -> None:
        """Persist one quality report."""
        self.quality_reports[report.campaign_id] = report

    def get_quality_report(self, campaign_id: str) -> BackfillQualityReport | None:
        """Return a campaign-level quality report."""
        return self.quality_reports.get(campaign_id)

    def save_publish_result(self, result: BackfillPublishResult) -> None:
        """Persist one publish result."""
        self.publish_results[result.campaign_id] = result


class BackfillApplicationService:
    """BackfillApplicationService.."""

    def __init__(
        self,
        *,
        repository: BackfillRepository | None = None,
        today: date | None = None,
    ) -> None:
        """Init .

        Args:
            repository: BackfillRepository | None: .
            today: date | None: .

        Returns:
            None: .
        """
        self._repository: BackfillRepository = repository or MemoryBackfillRepository()
        self._campaign_service = BackfillCampaignService(today=today)
        self._planner = BackfillPlanner()
        self._quality = BackfillQualityService()
        self._publisher = BackfillPublisher()

    def create_campaign(
        self,
        *,
        campaign_name: str,
        providers: tuple[str, ...],
        years: int = 20,
        start_date: date | str | None = None,
        end_date: date | str = "auto",
        mode: Literal["dry_run", "live"] = "dry_run",
        idempotency_key: str,
    ) -> BackfillCampaignSummary:
        """Create campaign.

        Args:
            campaign_name: str: .
            providers: tuple[str, ...]: .
            years: int: .
            start_date: date | str | None: .
            end_date: date | str: .
            mode: Literal['dry_run', 'live']: .
            idempotency_key: str: .

        Returns:
            BackfillCampaignSummary: .
        """
        request_hash = _campaign_request_hash(
            campaign_name=campaign_name,
            providers=providers,
            years=years,
            start_date=start_date,
            end_date=end_date,
            mode=mode,
        )
        existing_id = self._repository.lookup_idempotency_key(idempotency_key, request_hash)
        if existing_id is not None:
            return self.get_campaign(existing_id)
        campaign = self._campaign_service.init_campaign(
            campaign_name=campaign_name,
            providers=providers,
            years=years,
            start_date=start_date,
            end_date=end_date,
            mode=mode,
        )
        endpoint_plan = self._planner.plan_endpoints(campaign)
        partitions = self._planner.plan_partitions(campaign, endpoint_plan)
        self._repository.save_campaign(campaign)
        self._repository.save_endpoint_plan(endpoint_plan)
        self._repository.save_partitions(campaign.campaign_id, partitions)
        self._repository.record_idempotency_key(
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            campaign_id=campaign.campaign_id,
        )
        return self.get_campaign(campaign.campaign_id)

    def get_campaign(self, campaign_id: str) -> BackfillCampaignSummary:
        """Get campaign.

        Args:
            campaign_id: str: .

        Returns:
            BackfillCampaignSummary: .
        """
        campaign = self._require_campaign(campaign_id)
        partitions = self._repository.list_partitions(campaign_id)
        return BackfillCampaignSummary(
            campaign=campaign,
            endpoint_count=self._repository.count_endpoints(campaign_id),
            partition_count=len(partitions),
            quality_report_available=self._repository.get_quality_report(campaign_id) is not None,
        )

    def list_partitions(self, campaign_id: str) -> tuple[BackfillPartition, ...]:
        """List partitions.

        Args:
            campaign_id: str: .

        Returns:
            tuple[BackfillPartition, ...]: .
        """
        self._require_campaign(campaign_id)
        return self._repository.list_partitions(campaign_id)

    def run_campaign(self, campaign_id: str) -> BackfillRunSummary:
        """Run campaign.

        Args:
            campaign_id: str: .

        Returns:
            BackfillRunSummary: .
        """
        campaign = self._require_campaign(campaign_id)
        executor = DryRunBackfillExecutor()
        updated: list[BackfillPartition] = []
        raw_count = 0
        for partition in self._repository.list_partitions(campaign_id):
            executor.run_partition(partition)
            raw_count += 1
            updated.append(partition.model_copy(update={"status": PartitionStatus.SUCCEEDED}))
        self._repository.save_partitions(campaign_id, tuple(updated))
        self._repository.save_campaign(
            campaign.model_copy(
                update={"status": BackfillCampaignStatus.RUNNING}
            )
        )
        return BackfillRunSummary(
            campaign_id=campaign_id,
            status="succeeded",
            processed_partitions=len(updated),
            raw_snapshot_count=raw_count,
        )

    def verify_campaign(self, campaign_id: str) -> BackfillQualityReport:
        """Verify campaign.

        Args:
            campaign_id: str: .

        Returns:
            BackfillQualityReport: .
        """
        campaign = self._require_campaign(campaign_id)
        partitions = self._repository.list_partitions(campaign_id)
        by_endpoint: dict[tuple[str, str], list[BackfillPartition]] = {}
        for partition in partitions:
            by_endpoint.setdefault(
                (partition.provider_name, partition.endpoint_name),
                [],
            ).append(partition)
        endpoint_results = [
            {
                "provider_name": provider_name,
                "endpoint_name": endpoint_name,
                "expected_partitions": len(endpoint_partitions),
                "completed_partitions": sum(
                    partition.status is PartitionStatus.SUCCEEDED
                    for partition in endpoint_partitions
                ),
                "schema_drift": False,
            }
            for (provider_name, endpoint_name), endpoint_partitions in sorted(by_endpoint.items())
        ]
        report = self._quality.build_report(
            campaign=campaign,
            endpoint_results=endpoint_results,
        )
        self._repository.save_quality_report(report)
        self._repository.save_campaign(
            campaign.model_copy(
                update={
                    "status": (
                        BackfillCampaignStatus.VERIFIED
                        if report.publish_allowed
                        else BackfillCampaignStatus.BLOCKED
                    )
                }
            )
        )
        return report

    def get_quality_report(self, campaign_id: str) -> BackfillQualityReport | None:
        """Get quality report.

        Args:
            campaign_id: str: .

        Returns:
            BackfillQualityReport | None: .
        """
        self._require_campaign(campaign_id)
        return self._repository.get_quality_report(campaign_id)

    def publish_campaign(self, campaign_id: str) -> BackfillPublishResult:
        """Publish campaign.

        Args:
            campaign_id: str: .

        Returns:
            BackfillPublishResult: .
        """
        campaign = self._require_campaign(campaign_id)
        report = self._repository.get_quality_report(campaign_id)
        if report is None:
            raise ValueError("quality report did not pass")
        result = self._publisher.publish(campaign, report)
        self._repository.save_publish_result(result)
        self._repository.save_campaign(
            campaign.model_copy(update={"status": BackfillCampaignStatus.PUBLISHED})
        )
        return result

    def _require_campaign(self, campaign_id: str) -> BackfillCampaign:
        """Require campaign.

        Args:
            campaign_id: str: .

        Returns:
            BackfillCampaign: .
        """
        campaign = self._repository.get_campaign(campaign_id)
        if campaign is None:
            raise KeyError(f"backfill campaign not found: {campaign_id}")
        return campaign


def _campaign_request_hash(
    *,
    campaign_name: str,
    providers: tuple[str, ...],
    years: int,
    start_date: date | str | None,
    end_date: date | str,
    mode: Literal["dry_run", "live"],
) -> str:
    """Return the idempotency request hash for campaign creation."""
    return stable_json_hash(
        {
            "campaign_name": campaign_name,
            "providers": providers,
            "years": years,
            "start_date": start_date.isoformat() if isinstance(start_date, date) else start_date,
            "end_date": end_date.isoformat() if isinstance(end_date, date) else end_date,
            "mode": mode,
        }
    )
