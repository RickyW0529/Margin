"""Tests for centralized prompt repository and renderer."""

from __future__ import annotations

import pytest

from margin.prompts.agent_runtime import agent_runtime_prompt_templates
from margin.prompts.guardrails import guardrail_prompt_templates
from margin.prompts.registry import PromptRegistry
from margin.prompts.renderer import PromptRenderer, PromptRenderError


def test_registry_loads_versioned_prompt_by_id() -> None:
    """Test registry_loads_versioned_prompt_by_id.

    Returns:
        None: .
    """
    registry = PromptRegistry(
        templates=[
            *agent_runtime_prompt_templates(),
            *guardrail_prompt_templates(),
        ]
    )

    template = registry.get("main_agent_scheduled_planner_v0.4")

    assert template.prompt_id == "main_agent_scheduled_planner_v0.4"
    assert template.version == "v0.4.0"
    assert [section.title for section in template.sections][:2] == [
        "ROLE",
        "FIXED_FLOW_RULES",
    ]


def test_renderer_requires_declared_variables() -> None:
    """Test renderer_requires_declared_variables.

    Returns:
        None: .
    """
    registry = PromptRegistry(templates=agent_runtime_prompt_templates())
    template = registry.get("main_agent_scheduled_planner_v0.4")

    with pytest.raises(PromptRenderError, match="missing prompt variables"):
        PromptRenderer().render(
            template,
            variables={
                "run_context": "{}",
                "step_definition_json": "{}",
            },
        )


def test_renderer_outputs_hashes_without_mutating_template() -> None:
    """Test renderer_outputs_hashes_without_mutating_template.

    Returns:
        None: .
    """
    registry = PromptRegistry(templates=agent_runtime_prompt_templates())
    template = registry.get("main_agent_scheduled_planner_v0.4")

    rendered = PromptRenderer().render(
        template,
        variables={
            "run_context": '{"run_id":"ar_1"}',
            "step_definition_json": '{"flow_id":"scheduled_stock_analysis"}',
            "expert_agent_cards": "[]",
            "artifact_summaries": "[]",
        },
    )

    assert rendered.prompt_id == template.prompt_id
    assert rendered.prompt_version == template.version
    assert rendered.prompt_hash.startswith("sha256:")
    assert rendered.rendered_input_hash.startswith("sha256:")
    assert "<run_context>" in rendered.text
    assert "{{run_context}}" not in rendered.text
