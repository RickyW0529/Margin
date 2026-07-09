"""Single write path for v1 Context Engineering records.

ContextPack structured data is owned by ``ContextRepository`` (agent schema).
Opaque runtime artifacts (readiness, answers, worker outputs) remain on
``AgentContextStore`` for the chat/API expansion path.

This module removes scattered dual-writes: ContextPack payloads are no longer
mirrored into the runtime artifact table on write. Readers that still request a
pack id as an artifact can reconstruct one via ``context_pack_as_artifact``.
"""

from __future__ import annotations

from margin.agent_runtime.context_store import (
    AgentContextStore,
    ContextArtifact,
    make_context_artifact,
)
from margin.agents.context.repository import ContextRepository
from margin.agents.protocol.models import ContextPack


class ContextPersistence:
    """Owns the split between structured packs and runtime artifacts."""

    def __init__(
        self,
        *,
        context_store: AgentContextStore,
        context_repository: ContextRepository,
    ) -> None:
        """Initialize with the two persistence backends."""
        self._context_store = context_store
        self._context_repository = context_repository

    def persist_runtime_artifact(self, artifact: ContextArtifact) -> None:
        """Persist one opaque runtime artifact (not a structured ContextPack)."""
        self._context_store.add_artifact(artifact)

    def persist_context_pack(
        self,
        pack: ContextPack,
        *,
        readiness_artifact: ContextArtifact | None = None,
    ) -> ContextPack:
        """Persist a structured ContextPack once, plus optional readiness artifact.

        The pack is written only to ``ContextRepository``. Lineage edges from the
        pack to readiness / chat-summary refs are recorded here.
        """
        if readiness_artifact is not None:
            self._context_store.add_artifact(readiness_artifact)
            self._context_repository.record_lineage_edge(
                run_id=pack.run_id,
                from_ref=pack.context_pack_id,
                to_ref=readiness_artifact.artifact_id,
                edge_type="source_ref",
            )
        self._context_repository.save_context_pack(pack)
        if pack.included_chat_summary_ref:
            self._context_repository.record_lineage_edge(
                run_id=pack.run_id,
                from_ref=pack.context_pack_id,
                to_ref=pack.included_chat_summary_ref,
                edge_type="source_ref",
            )
        return pack

    def get_runtime_artifact(self, artifact_id: str) -> ContextArtifact | None:
        """Return a runtime artifact, falling back to a ContextPack reconstruction."""
        artifact = self._context_store.get_artifact(artifact_id)
        if artifact is not None:
            return artifact
        pack = self._context_repository.get_context_pack(artifact_id)
        if pack is None:
            return None
        return context_pack_as_artifact(pack)


def context_pack_as_artifact(pack: ContextPack) -> ContextArtifact:
    """Project a structured ContextPack into a runtime ContextArtifact view."""
    return make_context_artifact(
        artifact_id=pack.context_pack_id,
        run_id=pack.run_id,
        artifact_type="context_pack",
        producer_agent=pack.target_agent or "MainAgent",
        payload_json=pack.model_dump(mode="json"),
        source_refs=(pack.included_chat_summary_ref or "chat_summary:none",),
    )
