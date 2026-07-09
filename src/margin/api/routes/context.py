"""Context Store read APIs for Agent and Dashboard clients."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from margin.agent_runtime.context_store import AgentContextStore
from margin.agent_runtime.models import ContextArtifact
from margin.agents.context.repository import ContextRepository
from margin.api.dependencies import get_agent_context_store, get_context_repository
from margin.api.serialization import safe_artifact_payload

router = APIRouter(prefix="/api/v1", tags=["context"])

ContextStoreDep = Annotated[AgentContextStore, Depends(get_agent_context_store)]
ContextRepositoryDep = Annotated[ContextRepository, Depends(get_context_repository)]


class SafeArtifactResponse(BaseModel):
    """Frontend-safe persisted Context Store artifact detail."""

    artifact_id: str
    run_id: str
    artifact_type: str
    producer_agent: str
    payload_json: dict[str, Any]
    payload_hash: str
    source_refs: list[str]
    evidence_refs: list[str]
    created_at: datetime


class ContextPackResponse(BaseModel):
    """ContextPack artifact response."""

    context_pack_id: str
    run_id: str
    scope: str
    created_for_agent: str
    pack_json: dict[str, Any]
    pack_hash: str
    facts: list[dict[str, Any]]
    omissions: list[dict[str, Any]]


class ContextGraphNodeResponse(BaseModel):
    """One safe node in a run-level context graph."""

    ref: str
    node_type: str
    artifact_type: str | None = None
    producer_agent: str | None = None
    payload_hash: str | None = None


class ContextGraphEdgeResponse(BaseModel):
    """One safe lineage edge in a run-level context graph."""

    from_ref: str
    to_ref: str
    edge_type: str


class RunContextGraphResponse(BaseModel):
    """Safe run-level context graph without artifact payloads."""

    run_id: str
    nodes: list[ContextGraphNodeResponse]
    edges: list[ContextGraphEdgeResponse]


@router.get(
    "/artifacts/{artifact_id}/safe",
    response_model=SafeArtifactResponse,
)
def get_safe_artifact(
    artifact_id: str,
    context_store: ContextStoreDep,
) -> SafeArtifactResponse:
    """Return one safe artifact view through the Context Store boundary.

    Args:
        artifact_id: Context artifact identifier.
        context_store: Persisted context store dependency.

    Returns:
        A redacted artifact payload plus immutable lineage fields.
    """
    artifact = context_store.get_artifact(artifact_id)
    if artifact is None:
        raise _not_found("context_artifact_not_found", "context artifact not found")
    return _artifact_to_safe_response(artifact)


@router.get(
    "/context-packs/{context_pack_id}",
    response_model=ContextPackResponse,
)
def get_context_pack(
    context_pack_id: str,
    context_repository: ContextRepositoryDep,
) -> ContextPackResponse:
    """Return a persisted ContextPack by id.

    Args:
        context_pack_id: ContextPack artifact identifier.
        context_repository: Structured Context repository dependency.

    Returns:
        A safe ContextPack response.
    """
    pack = context_repository.get_context_pack(context_pack_id)
    if pack is None:
        raise _not_found("context_pack_not_found", "context pack not found")
    return ContextPackResponse(
        context_pack_id=context_pack_id,
        run_id=pack.run_id,
        scope=pack.purpose,
        created_for_agent=pack.target_agent,
        pack_json=safe_artifact_payload(pack.model_dump(mode="json")),
        pack_hash=pack.payload_hash,
        facts=[
            safe_artifact_payload(fact.model_dump(mode="json"))
            for fact in context_repository.list_context_facts(context_pack_id)
        ],
        omissions=[
            omission.model_dump(mode="json")
            for omission in context_repository.list_context_omissions(context_pack_id)
        ],
    )


@router.get(
    "/runs/{run_id}/context-graph",
    response_model=RunContextGraphResponse,
)
def get_run_context_graph(
    run_id: str,
    context_store: ContextStoreDep,
    context_repository: ContextRepositoryDep,
) -> RunContextGraphResponse:
    """Return a run-level context lineage graph without raw artifact payloads.

    Args:
        run_id: Agent run identifier.
        context_store: Persisted context artifact store dependency.
        context_repository: Structured Context repository dependency.

    Returns:
        Artifact/source/evidence nodes and lineage edges for the run.
    """
    artifacts = context_store.list_artifacts(run_id)
    lineage_edges = context_repository.list_lineage_edges(run_id)
    if not artifacts and not lineage_edges:
        raise _not_found("agent_run_context_not_found", "agent run context not found")

    nodes_by_ref: dict[str, ContextGraphNodeResponse] = {}
    edges: list[ContextGraphEdgeResponse] = []
    for artifact in artifacts:
        nodes_by_ref[artifact.artifact_id] = ContextGraphNodeResponse(
            ref=artifact.artifact_id,
            node_type="artifact",
            artifact_type=artifact.artifact_type,
            producer_agent=artifact.producer_agent,
            payload_hash=artifact.payload_hash,
        )
    for edge in lineage_edges:
        nodes_by_ref.setdefault(
            edge.from_ref,
            ContextGraphNodeResponse(ref=edge.from_ref, node_type="artifact"),
        )
        nodes_by_ref.setdefault(
            edge.to_ref,
            ContextGraphNodeResponse(ref=edge.to_ref, node_type=edge.edge_type),
        )
        edges.append(
            ContextGraphEdgeResponse(
                from_ref=edge.from_ref,
                to_ref=edge.to_ref,
                edge_type=edge.edge_type,
            )
        )

    return RunContextGraphResponse(
        run_id=run_id,
        nodes=list(nodes_by_ref.values()),
        edges=edges,
    )


def _artifact_to_safe_response(artifact: ContextArtifact) -> SafeArtifactResponse:
    """Convert a context artifact to a safe API response.

    Args:
        artifact: Persisted context artifact.

    Returns:
        Redacted artifact response.
    """
    return SafeArtifactResponse(
        artifact_id=artifact.artifact_id,
        run_id=artifact.run_id,
        artifact_type=artifact.artifact_type,
        producer_agent=artifact.producer_agent,
        payload_json=safe_artifact_payload(artifact.payload_json),
        payload_hash=artifact.payload_hash,
        source_refs=list(artifact.source_refs),
        evidence_refs=list(artifact.evidence_refs),
        created_at=artifact.created_at,
    )


def _not_found(code: str, message: str) -> HTTPException:
    """Build a structured 404 response.

    Args:
        code: Stable error code.
        message: User-facing error message.

    Returns:
        FastAPI HTTPException.
    """
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": code, "message": message},
    )
