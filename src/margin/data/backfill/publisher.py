"""Publish guard for verified backfill campaigns."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from margin.data.backfill.campaign import BackfillCampaign
from margin.data.backfill.quality import BackfillQualityReport


class BackfillPublishResult(BaseModel):
    """BackfillPublishResult.."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    campaign_id: str
    status: str
    built_layers: tuple[str, ...]
    safe_summary: str


class BackfillPublisher:
    """BackfillPublisher.."""

    def publish(
        self,
        campaign: BackfillCampaign,
        quality_report: BackfillQualityReport,
    ) -> BackfillPublishResult:
        """Publish.

        Args:
            campaign: BackfillCampaign: .
            quality_report: BackfillQualityReport: .

        Returns:
            BackfillPublishResult: .
        """
        if quality_report.campaign_id != campaign.campaign_id:
            raise ValueError("quality report campaign_id mismatch")
        if not quality_report.publish_allowed:
            raise ValueError("quality report did not pass")
        return BackfillPublishResult(
            campaign_id=campaign.campaign_id,
            status="published",
            built_layers=("ods", "vault", "pit", "kimball", "mart"),
            safe_summary=(
                "Backfill publish accepted; ODS, Vault, PIT, Kimball, "
                "and Mart promotion stages recorded."
            ),
        )
