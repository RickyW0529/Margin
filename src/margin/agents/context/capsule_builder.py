"""DomainContextCapsule builder."""

from __future__ import annotations

from margin.agent_runtime.models import ContextArtifact
from margin.agents.context.fact_extractor import ContextFactExtractor
from margin.agents.protocol.models import (
    AgentExecutionStatus,
    DomainContextCapsule,
    DomainTaskRequest,
)
from margin.core.hashing import stable_json_hash

CAPSULE_POLICY_VERSION = "domain-capsule-builder-v1"


class DomainContextCapsuleBuilder:
    """DomainContextCapsuleBuilder.."""

    def __init__(self, extractor: ContextFactExtractor | None = None) -> None:
        """Init .

        Args:
            extractor: ContextFactExtractor | None: .

        Returns:
            None: .
        """
        self._extractor = extractor or ContextFactExtractor()

    def build(
        self,
        *,
        domain_task: DomainTaskRequest,
        artifacts: tuple[ContextArtifact, ...],
        token_budget: int,
    ) -> DomainContextCapsule:
        """Build.

        Args:
            domain_task: DomainTaskRequest: .
            artifacts: tuple[ContextArtifact, ...]: .
            token_budget: int: .

        Returns:
            DomainContextCapsule: .
        """
        del token_budget
        artifact_refs = tuple(artifact.artifact_id for artifact in artifacts)
        evidence_refs = tuple(
            dict.fromkeys(ref for artifact in artifacts for ref in artifact.evidence_refs)
        )
        source_refs = tuple(
            dict.fromkeys(ref for artifact in artifacts for ref in artifact.source_refs)
        )
        key_facts = tuple(
            fact for artifact in artifacts for fact in self._extractor.extract(artifact)
        )
        open_questions = tuple(
            gap
            for artifact in artifacts
            for gap in artifact.payload_json.get("gaps", ())
            if isinstance(gap, str)
        )
        conflicting_facts = tuple(
            conflict
            for artifact in artifacts
            for conflict in artifact.payload_json.get("conflicts", ())
            if isinstance(conflict, dict)
        )
        input_hash = stable_json_hash(
            {
                "domain_task_id": domain_task.domain_task_id,
                "artifact_refs": artifact_refs,
                "evidence_refs": evidence_refs,
                "source_refs": source_refs,
                "open_questions": open_questions,
                "conflicting_facts": conflicting_facts,
            }
        )
        return DomainContextCapsule(
            capsule_id=f"ctx_capsule_{domain_task.domain_task_id}",
            run_id=domain_task.run_id,
            domain=domain_task.domain,
            purpose=domain_task.task_goal,
            status=(AgentExecutionStatus.SUCCEEDED if artifacts else AgentExecutionStatus.BLOCKED),
            summary=f"{domain_task.domain} capsule from {len(artifacts)} artifacts.",
            key_facts=key_facts,
            evidence_refs=evidence_refs,
            source_refs=source_refs,
            artifact_refs=artifact_refs,
            open_questions=open_questions,
            conflicting_facts=conflicting_facts,
            compression_policy_version=CAPSULE_POLICY_VERSION,
            input_hash=input_hash,
        )
