"""ContextPack builder with conservative payload omission."""

from __future__ import annotations

from collections.abc import Iterable

from margin.agent_runtime.models import ContextArtifact
from margin.agents.protocol.models import ContextFact, ContextOmission, ContextPack

CONTEXT_POLICY_VERSION = "context-pack-v1"
_UNSAFE_KEYS = {
    "api_key",
    "authorization",
    "password",
    "provider_token",
    "raw_text",
    "secret",
    "system_prompt",
    "token",
}


class ContextRouter:
    """Build bounded ContextPacks from artifact indexes and summaries.."""

    def build_context_pack(
        self,
        *,
        run_id: str,
        requester_agent: str,
        target_agent: str,
        purpose: str,
        token_budget: int,
        artifacts: Iterable[ContextArtifact] = (),
        included_capsule_refs: tuple[str, ...] = (),
        included_chat_summary_ref: str | None = None,
    ) -> ContextPack:
        """Build a compact context pack without raw artifact payloads.

        Args:
            run_id: str: .
            requester_agent: str: .
            target_agent: str: .
            purpose: str: .
            token_budget: int: .
            artifacts: Iterable[ContextArtifact]: .
            included_capsule_refs: tuple[str, ...]: .
            included_chat_summary_ref: str | None: .

        Returns:
            ContextPack: .
        """
        included_artifact_refs: list[str] = []
        facts: list[ContextFact] = []
        evidence_refs: list[str] = []
        source_refs: list[str] = []
        omissions: list[ContextOmission] = []
        estimated_tokens = 0
        for artifact in artifacts:
            included_artifact_refs.append(artifact.artifact_id)
            evidence_refs.extend(artifact.evidence_refs)
            source_refs.extend(artifact.source_refs)
            statement = (
                f"{artifact.artifact_type} produced by {artifact.producer_agent}; "
                f"payload_hash={artifact.payload_hash}"
            )
            estimated_tokens += max(1, len(statement) // 4)
            if estimated_tokens > token_budget:
                omissions.append(
                    ContextOmission(
                        omitted_ref=artifact.artifact_id,
                        reason="token_budget",
                    )
                )
                continue
            facts.append(
                ContextFact(
                    fact_id=f"fact_{artifact.artifact_id}",
                    statement=statement,
                    confidence=1.0,
                    fact_type=_fact_type(artifact.artifact_type),
                    artifact_refs=(artifact.artifact_id,),
                    evidence_refs=artifact.evidence_refs,
                    source_refs=artifact.source_refs,
                    valid_at=artifact.created_at,
                )
            )
            for key in artifact.payload_json:
                if key.lower() in _UNSAFE_KEYS:
                    omissions.append(
                        ContextOmission(
                            omitted_ref=f"{artifact.artifact_id}:{key}",
                            reason="unsafe",
                        )
                    )
        return ContextPack(
            context_pack_id=f"ctxpack_{run_id}_{target_agent.lower()}",
            run_id=run_id,
            requester_agent=requester_agent,
            target_agent=target_agent,
            purpose=purpose,
            token_budget=token_budget,
            included_artifact_refs=tuple(dict.fromkeys(included_artifact_refs)),
            included_capsule_refs=included_capsule_refs,
            included_chat_summary_ref=included_chat_summary_ref,
            facts=tuple(facts),
            evidence_refs=tuple(dict.fromkeys(evidence_refs)),
            source_refs=tuple(dict.fromkeys(source_refs)),
            omissions=tuple(omissions),
            compression_policy_version=CONTEXT_POLICY_VERSION,
        )


def _fact_type(artifact_type: str) -> str:
    """Process _fact_type.

    Args:
        artifact_type: str: .

    Returns:
        str: .
    """
    if "quant" in artifact_type:
        return "quant_signal"
    if "risk" in artifact_type:
        return "risk_flag"
    if "evidence" in artifact_type or "citation" in artifact_type:
        return "evidence_claim"
    if "data" in artifact_type:
        return "data_status"
    return "metric"
