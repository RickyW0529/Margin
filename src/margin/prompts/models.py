"""Versioned prompt models for centralized prompt management."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PromptKind(StrEnum):
    """Supported prompt categories.."""

    MAIN_AGENT = "main_agent"
    EXPERT_AGENT = "expert_agent"
    EXPERT_AGENT_BASE = "expert_agent_base"
    GUARDRAIL = "guardrail"


class PromptSection(BaseModel):
    """One named prompt section.."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str
    content: str

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        """Normalize section titles for stable prompt hashes.

        Args:
            value: str: .

        Returns:
            str: .
        """
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("section title cannot be empty")
        return normalized


class PromptTemplate(BaseModel):
    """A versioned prompt template.."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt_id: str
    version: str
    kind: PromptKind
    model_profile: str
    temperature: float = Field(ge=0.0, le=2.0)
    purpose: str
    sections: tuple[PromptSection, ...]
    output_schema: dict[str, Any] = Field(default_factory=dict)

    @property
    def required_variables(self) -> tuple[str, ...]:
        """Return unique template variables referenced by section content.

        Returns:
            tuple[str, ...]: .
        """
        variables: list[str] = []
        for section in self.sections:
            start = 0
            while True:
                left = section.content.find("{{", start)
                if left < 0:
                    break
                right = section.content.find("}}", left + 2)
                if right < 0:
                    break
                name = section.content[left + 2 : right].strip()
                if name and name not in variables:
                    variables.append(name)
                start = right + 2
        return tuple(variables)

    @property
    def template_hash(self) -> str:
        """Return a stable hash of template content and metadata.

        Returns:
            str: .
        """
        payload = self.model_dump(mode="json")
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
        return f"sha256:{hashlib.sha256(raw).hexdigest()}"


class RenderedPrompt(BaseModel):
    """Rendered prompt text and audit hashes.."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt_id: str
    prompt_version: str
    model_profile: str
    temperature: float
    text: str
    prompt_hash: str
    rendered_input_hash: str
    output_schema: dict[str, Any] = Field(default_factory=dict)
