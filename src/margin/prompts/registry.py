"""Versioned prompt registry."""

from __future__ import annotations

from collections.abc import Iterable

from margin.prompts.models import PromptTemplate


class PromptNotFoundError(KeyError):
    """Raised when a prompt template is missing."""


class PromptRegistry:
    """In-memory registry of versioned prompt templates."""

    def __init__(self, templates: Iterable[PromptTemplate]) -> None:
        """Initialize registry.

        Args:
            templates: Prompt templates to register.

        Raises:
            ValueError: If a prompt id is duplicated.
        """
        self._templates: dict[str, PromptTemplate] = {}
        for template in templates:
            existing = self._templates.get(template.prompt_id)
            if existing is not None:
                raise ValueError(f"duplicate prompt_id: {template.prompt_id}")
            self._templates[template.prompt_id] = template

    def get(self, prompt_id: str) -> PromptTemplate:
        """Return a prompt template by stable prompt id."""
        try:
            return self._templates[prompt_id]
        except KeyError as exc:
            raise PromptNotFoundError(prompt_id) from exc

    def list_ids(self) -> tuple[str, ...]:
        """Return registered prompt ids in stable order."""
        return tuple(sorted(self._templates))
