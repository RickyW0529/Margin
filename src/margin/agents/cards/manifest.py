"""Versioned, data-driven Agent card manifests."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources

from pydantic import BaseModel, ConfigDict

from margin.agents.cards.domain_cards import DomainAgentCard
from margin.agents.cards.worker_cards import WorkerAgentCard


class AgentCardManifest(BaseModel):
    """One immutable set of domain and worker cards for a runtime profile."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest_version: str
    profile: str
    domain_agents: tuple[DomainAgentCard, ...]
    worker_agents: tuple[WorkerAgentCard, ...]


@lru_cache(maxsize=8)
def load_agent_card_manifest(profile: str = "user_qna") -> AgentCardManifest:
    """Load a packaged card manifest by profile name."""
    if not profile or not profile.replace("_", "").isalnum():
        raise ValueError("invalid Agent card profile")
    resource = resources.files("margin.agents.cards.manifests").joinpath(
        f"{profile}.json"
    )
    if not resource.is_file():
        raise ValueError(f"unknown Agent card profile: {profile}")
    payload = json.loads(resource.read_text(encoding="utf-8"))
    manifest = AgentCardManifest.model_validate(payload)
    if manifest.profile != profile:
        raise ValueError("Agent card manifest profile mismatch")
    return manifest

