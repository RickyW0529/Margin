"""Deterministic domain context compression."""

from __future__ import annotations

from margin.agent_runtime.context_store import stable_json_hash
from margin.agent_runtime.models import ContextArtifact
from margin.agents.protocol.models import (
    AgentExecutionStatus,
    ContextFact,
    DomainContextCapsule,
    DomainTaskRequest,
)

COMPRESSION_POLICY_VERSION = "domain-capsule-v1"


class DeterministicDomainCompressor:
    """Build a structured capsule from worker artifact references."""

    def compress(
        self,
        *,
        domain_task: DomainTaskRequest,
        worker_artifacts: tuple[ContextArtifact, ...],
        token_budget: int,
    ) -> DomainContextCapsule:
        """Compress worker artifacts into an auditable domain capsule."""
        del token_budget
        artifact_refs = tuple(artifact.artifact_id for artifact in worker_artifacts)
        evidence_refs = tuple(
            dict.fromkeys(
                ref
                for artifact in worker_artifacts
                for ref in artifact.evidence_refs
            )
        )
        source_refs = tuple(
            dict.fromkeys(
                ref
                for artifact in worker_artifacts
                for ref in artifact.source_refs
            )
        )
        facts = tuple(
            ContextFact(
                fact_id=f"fact_{artifact.artifact_id}",
                statement=(
                    f"{artifact.artifact_type} produced by {artifact.producer_agent}"
                ),
                confidence=1.0,
                fact_type="metric",
                artifact_refs=(artifact.artifact_id,),
                evidence_refs=artifact.evidence_refs,
                source_refs=artifact.source_refs,
                valid_at=artifact.created_at,
            )
            for artifact in worker_artifacts
        )
        status = (
            AgentExecutionStatus.SUCCEEDED
            if worker_artifacts
            else AgentExecutionStatus.BLOCKED
        )
        input_hash = stable_json_hash(
            {
                "domain_task_id": domain_task.domain_task_id,
                "artifact_refs": artifact_refs,
                "evidence_refs": evidence_refs,
                "source_refs": source_refs,
            }
        )
        return DomainContextCapsule(
            capsule_id=f"ctx_capsule_{domain_task.domain_task_id}",
            run_id=domain_task.run_id,
            domain=domain_task.domain,
            purpose=domain_task.task_goal,
            status=status,
            summary=(
                f"{domain_task.domain} domain produced {len(worker_artifacts)} artifacts."
            ),
            key_facts=facts,
            evidence_refs=evidence_refs,
            source_refs=source_refs,
            artifact_refs=artifact_refs,
            compression_policy_version=COMPRESSION_POLICY_VERSION,
            input_hash=input_hash,
        )
