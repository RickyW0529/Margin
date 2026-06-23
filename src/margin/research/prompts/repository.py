"""Prompt template and render-hash audit repository contracts."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from margin.research.prompts.factory import PromptKind


class PromptTemplateRecord(BaseModel):
    """Immutable metadata for a node prompt template."""

    node_name: str
    kind: PromptKind
    version: str
    template_hash: str

    model_config = {"frozen": True}


class PromptRepository(Protocol):
    """Metadata-only persistence contract; full prompt text is excluded."""

    def get_template(
        self,
        node_name: str,
        kind: PromptKind,
    ) -> PromptTemplateRecord | None:
        """Return template metadata."""

    def record_rendered_prompt_hash(self, call_id: str, prompt_hash: str) -> None:
        """Associate an LLM call with a rendered prompt hash."""


class MemoryPromptRepository:
    """Append-only in-memory prompt metadata repository."""

    def __init__(self) -> None:
        """Initialize the instance."""
        self._templates: dict[tuple[str, PromptKind], PromptTemplateRecord] = {}
        self._render_audits: dict[str, dict[str, str]] = {}

    def register_template(
        self,
        *,
        node_name: str,
        kind: PromptKind,
        version: str,
        template_hash: str,
    ) -> None:
        """Register immutable template metadata."""
        key = (node_name, kind)
        record = PromptTemplateRecord(
            node_name=node_name,
            kind=kind,
            version=version,
            template_hash=template_hash,
        )
        current = self._templates.get(key)
        if current is not None and current != record:
            raise ValueError(f"prompt template '{node_name}/{kind.value}' is immutable")
        self._templates[key] = record

    def get_template(
        self,
        node_name: str,
        kind: PromptKind,
    ) -> PromptTemplateRecord | None:
        """Return template metadata."""
        return self._templates.get((node_name, kind))

    def record_rendered_prompt_hash(self, call_id: str, prompt_hash: str) -> None:
        """Record only the prompt hash for an LLM call."""
        record = {"prompt_hash": prompt_hash}
        current = self._render_audits.get(call_id)
        if current is not None and current != record:
            raise ValueError(f"prompt render audit '{call_id}' is immutable")
        self._render_audits[call_id] = record

    def get_render_audit(self, call_id: str) -> dict[str, str] | None:
        """Return a defensive copy of prompt render metadata."""
        record = self._render_audits.get(call_id)
        return dict(record) if record is not None else None
