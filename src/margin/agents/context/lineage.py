"""Lineage validation helpers for Agent artifacts."""

from __future__ import annotations

from dataclasses import dataclass

from margin.agent_runtime.context_store import stable_json_hash
from margin.agent_runtime.models import ContextArtifact


@dataclass(frozen=True)
class ArtifactLineageCheck:
    """Result of validating one ContextArtifact."""

    artifact_id: str
    valid: bool
    problems: tuple[str, ...] = ()


class ArtifactLineageValidator:
    """Validate immutable artifact hashes and expected producer/type contracts."""

    def validate(
        self,
        artifact: ContextArtifact,
        *,
        expected_producer: str | None = None,
        expected_artifact_type: str | None = None,
    ) -> ArtifactLineageCheck:
        """Return whether an artifact satisfies basic lineage checks."""
        problems: list[str] = []
        if stable_json_hash(artifact.payload_json) != artifact.payload_hash:
            problems.append("payload_hash_mismatch")
        if expected_producer is not None and artifact.producer_agent != expected_producer:
            problems.append("producer_mismatch")
        if (
            expected_artifact_type is not None
            and artifact.artifact_type != expected_artifact_type
        ):
            problems.append("artifact_type_mismatch")
        return ArtifactLineageCheck(
            artifact_id=artifact.artifact_id,
            valid=not problems,
            problems=tuple(problems),
        )
