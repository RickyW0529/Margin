"""Prompt rendering and hashing."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from margin.prompts.models import PromptTemplate, RenderedPrompt


class PromptRenderError(ValueError):
    """Raised when prompt rendering fails.."""


class PromptRenderer:
    """Render versioned prompt templates with explicit variable injection.."""

    def render(
        self,
        template: PromptTemplate,
        *,
        variables: Mapping[str, object],
    ) -> RenderedPrompt:
        """Render a template with variables.

        Args:
            template: PromptTemplate: .
            variables: Mapping[str, object]: .

        Returns:
            RenderedPrompt: .
        """
        missing = [name for name in template.required_variables if name not in variables]
        if missing:
            raise PromptRenderError("missing prompt variables: " + ", ".join(sorted(missing)))

        rendered_sections: list[str] = []
        for section in template.sections:
            content = section.content
            for name in template.required_variables:
                content = content.replace(
                    "{{" + name + "}}",
                    self._stringify(variables[name]),
                )
            rendered_sections.append(f"## {section.title}\n{content}")
        text = "\n\n".join(rendered_sections)
        return RenderedPrompt(
            prompt_id=template.prompt_id,
            prompt_version=template.version,
            model_profile=template.model_profile,
            temperature=template.temperature,
            text=text,
            prompt_hash=template.template_hash,
            rendered_input_hash=self._hash_json(
                {
                    "prompt_id": template.prompt_id,
                    "prompt_version": template.version,
                    "variables": variables,
                }
            ),
            output_schema=template.output_schema,
        )

    def _stringify(self, value: object) -> str:
        """Serialize a variable for prompt insertion.

        Args:
            value: object: .

        Returns:
            str: .
        """
        if isinstance(value, str):
            return value
        return json.dumps(value, sort_keys=True, ensure_ascii=False)

    def _hash_json(self, payload: object) -> str:
        """Return a stable JSON hash.

        Args:
            payload: object: .

        Returns:
            str: .
        """
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        return f"sha256:{hashlib.sha256(raw.encode()).hexdigest()}"
