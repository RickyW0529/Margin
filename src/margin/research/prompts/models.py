"""Immutable rendered-prompt models."""

from __future__ import annotations

import hashlib

from pydantic import BaseModel


class PromptSection(BaseModel):
    """One ordered prompt section.."""

    title: str
    content: str

    model_config = {"frozen": True}


class RenderedPrompt(BaseModel):
    """Versioned prompt with deterministic rendering and hashing.."""

    node_name: str
    kind: str
    prompt_version: str
    sections: tuple[PromptSection, ...]

    model_config = {"frozen": True}

    def render(self) -> str:
        """Render sections without changing their precedence.

        Returns:
            str: .
        """
        return "\n\n".join(f"## {section.title}\n{section.content}" for section in self.sections)

    @property
    def prompt_hash(self) -> str:
        """Return a deterministic hash without persisting prompt text.

        Returns:
            str: .
        """
        return "sha256:" + hashlib.sha256(self.render().encode("utf-8")).hexdigest()
