"""Dry-run execution primitives for deterministic backfill partitions."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from margin.core.hashing import stable_json_hash
from margin.data.backfill.planner import BackfillPartition, PartitionStatus


class RawSnapshotMetadata(BaseModel):
    """RawSnapshotMetadata.."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    raw_snapshot_id: str
    provider_name: str
    endpoint_name: str
    partition_id: str
    fetched_at: datetime
    available_at: datetime
    row_count: int = Field(ge=0)
    payload_hash: str
    payload_fingerprint: dict[str, str]


class BackfillPartitionResult(BaseModel):
    """BackfillPartitionResult.."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    partition_id: str
    status: PartitionStatus
    raw_snapshot: RawSnapshotMetadata
    retryable: bool = False
    safe_summary: str


class DryRunBackfillExecutor:
    """DryRunBackfillExecutor.."""

    def __init__(self, *, fetched_at: datetime | None = None) -> None:
        """Init .

        Args:
            fetched_at: datetime | None: .

        Returns:
            None: .
        """
        self._fetched_at = fetched_at or datetime.now(UTC)

    def run_partition(self, partition: BackfillPartition) -> BackfillPartitionResult:
        """Run partition.

        Args:
            partition: BackfillPartition: .

        Returns:
            BackfillPartitionResult: .
        """
        fingerprint = {
            "provider_name": partition.provider_name,
            "endpoint_name": partition.endpoint_name,
            "partition_id": partition.partition_id,
            "params_hash": partition.params_hash,
        }
        payload_hash = stable_json_hash(fingerprint)
        raw_snapshot_id = f"raw_{payload_hash.removeprefix('sha256:')[:24]}"
        return BackfillPartitionResult(
            partition_id=partition.partition_id,
            status=PartitionStatus.SUCCEEDED,
            raw_snapshot=RawSnapshotMetadata(
                raw_snapshot_id=raw_snapshot_id,
                provider_name=partition.provider_name,
                endpoint_name=partition.endpoint_name,
                partition_id=partition.partition_id,
                fetched_at=self._fetched_at,
                available_at=self._fetched_at,
                row_count=0,
                payload_hash=payload_hash,
                payload_fingerprint=fingerprint,
            ),
            safe_summary="Dry-run partition metadata generated; no provider data fetched.",
        )
