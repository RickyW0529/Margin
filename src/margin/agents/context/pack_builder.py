"""Full v1 ContextPack builder."""

from __future__ import annotations

from collections.abc import Iterable

from margin.agent_runtime.models import ContextArtifact
from margin.agents.context.budget import estimate_fact_tokens
from margin.agents.context.fact_extractor import ContextFactExtractor, chat_memory_fact
from margin.agents.context.ranker import ContextFactRanker
from margin.agents.protocol.models import ContextFact, ContextOmission, ContextPack
from margin.agents.security.capability import CapabilityToken

CONTEXT_POLICY_VERSION = "context-pack-builder-v1"
UNSAFE_KEYS = {
    "api_key",
    "authorization",
    "password",
    "provider_token",
    "raw_text",
    "secret",
    "system_prompt",
    "token",
}


class ContextPackBuilder:
    """ContextPackBuilder.."""

    def __init__(
        self,
        *,
        extractor: ContextFactExtractor | None = None,
        ranker: ContextFactRanker | None = None,
    ) -> None:
        """Init .

        Args:
            extractor: ContextFactExtractor | None: .
            ranker: ContextFactRanker | None: .

        Returns:
            None: .
        """
        self._extractor = extractor or ContextFactExtractor()
        self._ranker = ranker or ContextFactRanker()

    def build(
        self,
        *,
        run_id: str,
        requester_agent: str,
        target_agent: str,
        purpose: str,
        user_goal: str,
        capability_token: CapabilityToken,
        artifacts: Iterable[ContextArtifact] = (),
        chat_memory_summary: str | None = None,
        token_budget: int,
    ) -> ContextPack:
        """Build.

        Args:
            run_id: str: .
            requester_agent: str: .
            target_agent: str: .
            purpose: str: .
            user_goal: str: .
            capability_token: CapabilityToken: .
            artifacts: Iterable[ContextArtifact]: .
            chat_memory_summary: str | None: .
            token_budget: int: .

        Returns:
            ContextPack: .
        """
        candidate_facts: list[ContextFact] = []
        included_artifact_refs: list[str] = []
        evidence_refs: list[str] = []
        source_refs: list[str] = []
        omissions: list[ContextOmission] = []

        if chat_memory_summary:
            candidate_facts.append(chat_memory_fact(chat_memory_summary))

        for artifact in artifacts:
            if (
                capability_token.allowed_artifact_types
                and artifact.artifact_type not in capability_token.allowed_artifact_types
            ):
                omissions.append(
                    ContextOmission(
                        omitted_ref=artifact.artifact_id,
                        reason="not_authorized",
                    )
                )
                continue
            included_artifact_refs.append(artifact.artifact_id)
            evidence_refs.extend(artifact.evidence_refs)
            source_refs.extend(artifact.source_refs)
            unsafe_index = 0
            for key in artifact.payload_json:
                if key.lower() in UNSAFE_KEYS:
                    unsafe_index += 1
                    omissions.append(
                        ContextOmission(
                            omitted_ref=f"{artifact.artifact_id}:unsafe_field_{unsafe_index}",
                            reason="unsafe",
                        )
                    )
            candidate_facts.extend(self._extractor.extract(artifact))

        facts: list[ContextFact] = []
        used_tokens = max(1, len(user_goal) // 4)
        for fact in self._ranker.rank(tuple(candidate_facts)):
            fact_tokens = estimate_fact_tokens(fact)
            if used_tokens + fact_tokens > token_budget:
                for artifact_ref in fact.artifact_refs or (fact.fact_id,):
                    omissions.append(
                        ContextOmission(
                            omitted_ref=artifact_ref,
                            reason="token_budget",
                        )
                    )
                continue
            facts.append(fact)
            used_tokens += fact_tokens

        return ContextPack(
            context_pack_id=f"ctxpack_{run_id}_{target_agent.lower()}",
            run_id=run_id,
            requester_agent=requester_agent,
            target_agent=target_agent,
            purpose=purpose,
            token_budget=token_budget,
            included_artifact_refs=tuple(dict.fromkeys(included_artifact_refs)),
            facts=tuple(facts),
            evidence_refs=tuple(dict.fromkeys(evidence_refs)),
            source_refs=tuple(dict.fromkeys(source_refs)),
            omissions=tuple(omissions),
            compression_policy_version=CONTEXT_POLICY_VERSION,
        )
