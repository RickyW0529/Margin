"""Prompt bundle models."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PromptTemplate(BaseModel):
    """PromptTemplate.."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt_id: str
    version: str
    role: Literal["system", "developer", "user", "tool"]
    template_text: str
    allowed_variables: tuple[str, ...] = ()
    output_schema_ref: str | None = None
    safety_tags: tuple[str, ...] = ()


class PromptBundle(BaseModel):
    """PromptBundle.."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt_bundle_id: str
    version: str
    target_agent_type: Literal["main", "domain_expert", "worker", "validator", "compressor"]
    templates: tuple[PromptTemplate, ...]
    model_profile_ref: str
    max_output_tokens: int = Field(ge=1)
    temperature: float = Field(ge=0, le=2)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
