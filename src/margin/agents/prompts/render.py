"""Prompt rendering with strict variable checks and hash history."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from margin.agent_runtime.context_store import stable_json_hash
from margin.agents.prompts.bundles import PromptBundle

_VARIABLE_PATTERN = re.compile(r"{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}")


class PromptRenderRecord(BaseModel):
    """PromptRenderRecord.."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    render_id: str
    run_id: str
    task_id: str | None
    agent_name: str
    prompt_bundle_id: str
    prompt_hash: str
    variables_hash: str
    rendered_messages: tuple[dict[str, str], ...]
    rendered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PromptRenderer:
    """PromptRenderer.."""

    def __init__(self) -> None:
        """Init .

        Returns:
            None: .
        """
        self.history: dict[str, PromptRenderRecord] = {}

    def render_bundle(
        self,
        bundle: PromptBundle,
        *,
        run_id: str,
        task_id: str | None,
        agent_name: str,
        variables: dict[str, Any],
    ) -> PromptRenderRecord:
        """Render bundle.

        Args:
            bundle: PromptBundle: .
            run_id: str: .
            task_id: str | None: .
            agent_name: str: .
            variables: dict[str, Any]: .

        Returns:
            PromptRenderRecord: .
        """
        required_variables = {
            variable
            for template in bundle.templates
            for variable in _VARIABLE_PATTERN.findall(template.template_text)
        }
        allowed_variables = {
            variable for template in bundle.templates for variable in template.allowed_variables
        }
        missing = sorted(required_variables - set(variables))
        extra = sorted(set(variables) - allowed_variables)
        if missing:
            raise ValueError("missing prompt variables: " + ", ".join(missing))
        if extra:
            raise ValueError("unexpected prompt variables: " + ", ".join(extra))
        messages: list[dict[str, str]] = []
        for template in bundle.templates:
            content = template.template_text
            for key, value in variables.items():
                content = re.sub(
                    r"{{\s*" + re.escape(key) + r"\s*}}",
                    str(value),
                    content,
                )
            messages.append({"role": template.role, "content": content})
        record = PromptRenderRecord(
            render_id=f"pr_{run_id}_{agent_name}_{len(self.history):04d}",
            run_id=run_id,
            task_id=task_id,
            agent_name=agent_name,
            prompt_bundle_id=bundle.prompt_bundle_id,
            prompt_hash=stable_json_hash(messages),
            variables_hash=stable_json_hash(variables),
            rendered_messages=tuple(messages),
        )
        self.history[record.render_id] = record
        return record
