"""NodeExecutionRunner with deterministic validation and bounded reflection."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel, Field

from margin.research.execution.llm_service import StructuredLLMResponse
from margin.research.execution.reflection import (
    REFLECTION_SCHEMA,
    NodeReflection,
    ReflectionAction,
)
from margin.research.prompts.models import PromptSection, RenderedPrompt


class DeterministicValidation(BaseModel):
    """Result of mandatory non-LLM node output validation."""

    valid: bool
    issues: tuple[str, ...] = Field(default_factory=tuple)

    model_config = {"frozen": True}


class OutputValidator(Protocol):
    """Validator called after every draft or revision."""

    def validate(
        self,
        *,
        node_name: str,
        output: dict[str, Any],
        output_schema: dict[str, Any],
    ) -> DeterministicValidation:
        """Validate one structured node output."""


class StructuredLLM(Protocol):
    """LLM boundary consumed by the runner."""

    def complete_structured(self, **kwargs: Any) -> StructuredLLMResponse:
        """Return one structured completion."""


class NodeExecutionResult(BaseModel):
    """Bounded node execution result."""

    output: dict[str, Any] = Field(default_factory=dict)
    validation: DeterministicValidation | None = None
    reflection: NodeReflection | None = None
    revision_count: int = 0
    evidence_gap_requested: bool = False
    abstained: bool = False
    error_code: str | None = None
    llm_call_ids: tuple[str, ...] = Field(default_factory=tuple)

    model_config = {"frozen": True}


class NodeExecutionRunner:
    """Run draft, validation, optional critic, and at most one revision."""

    def __init__(self, *, llm: StructuredLLM, validator: OutputValidator) -> None:
        """Initialize the instance."""
        self._llm = llm
        self._validator = validator

    def run_llm_node(
        self,
        *,
        graph_run_id: str,
        node_name: str,
        prompt: RenderedPrompt,
        output_schema: dict[str, Any],
        reflection_policy: str,
        deadline: datetime | None = None,
    ) -> NodeExecutionResult:
        """Execute one bounded LLM node."""
        draft = self._call(
            prompt=prompt,
            output_schema=output_schema,
            task_type="draft",
            node_name=node_name,
            graph_run_id=graph_run_id,
            deadline=deadline,
        )
        call_ids = [draft.call_id]
        if not draft.success:
            return NodeExecutionResult(
                abstained=True,
                error_code=draft.error_code or "draft_failed",
                llm_call_ids=tuple(call_ids),
            )
        validation = self._validator.validate(
            node_name=node_name,
            output=draft.output,
            output_schema=output_schema,
        )
        if node_name == "targeted_reanalysis":
            return NodeExecutionResult(
                output=draft.output,
                validation=validation,
                abstained=not validation.valid,
                error_code=None if validation.valid else "deterministic_validation_failed",
                llm_call_ids=tuple(call_ids),
            )
        critic_required = reflection_policy == "forced" or (
            reflection_policy == "conditional" and not validation.valid
        )
        if not critic_required:
            return NodeExecutionResult(
                output=draft.output,
                validation=validation,
                abstained=not validation.valid,
                error_code=None if validation.valid else "deterministic_validation_failed",
                llm_call_ids=tuple(call_ids),
            )

        critic = self._call(
            prompt=_derive_prompt(
                prompt,
                kind="reflection",
                draft=draft.output,
            ),
            output_schema=REFLECTION_SCHEMA,
            task_type="reflection",
            node_name=node_name,
            graph_run_id=graph_run_id,
            deadline=deadline,
        )
        call_ids.append(critic.call_id)
        if not critic.success:
            return NodeExecutionResult(
                output=draft.output,
                validation=validation,
                abstained=True,
                error_code=critic.error_code or "reflection_failed",
                llm_call_ids=tuple(call_ids),
            )
        reflection = NodeReflection.model_validate(critic.output)
        existing_evidence_ids = set(draft.output.get("evidence_ids", []))
        if not reflection.preserves_evidence(existing_evidence_ids):
            return NodeExecutionResult(
                output=draft.output,
                validation=validation,
                reflection=reflection,
                abstained=True,
                error_code="reflection_evidence_violation",
                llm_call_ids=tuple(call_ids),
            )
        if reflection.action == ReflectionAction.NEEDS_EVIDENCE:
            return NodeExecutionResult(
                output=draft.output,
                validation=validation,
                reflection=reflection,
                evidence_gap_requested=True,
                llm_call_ids=tuple(call_ids),
            )
        if reflection.action == ReflectionAction.ABSTAIN:
            return NodeExecutionResult(
                output=draft.output,
                validation=validation,
                reflection=reflection,
                abstained=True,
                error_code="critic_abstained",
                llm_call_ids=tuple(call_ids),
            )
        if reflection.action == ReflectionAction.ACCEPT:
            return NodeExecutionResult(
                output=draft.output,
                validation=validation,
                reflection=reflection,
                abstained=not validation.valid,
                error_code=(
                    None
                    if validation.valid
                    else "deterministic_validation_failed"
                ),
                llm_call_ids=tuple(call_ids),
            )

        revision = self._call(
            prompt=_derive_prompt(
                prompt,
                kind="revision",
                draft=draft.output,
                reflection=reflection.model_dump(mode="json"),
            ),
            output_schema=output_schema,
            task_type="revision",
            node_name=node_name,
            graph_run_id=graph_run_id,
            deadline=deadline,
        )
        call_ids.append(revision.call_id)
        if not revision.success:
            return NodeExecutionResult(
                output=draft.output,
                validation=validation,
                reflection=reflection,
                abstained=True,
                error_code=revision.error_code or "revision_failed",
                llm_call_ids=tuple(call_ids),
            )
        if not set(revision.output.get("evidence_ids", [])) <= existing_evidence_ids:
            return NodeExecutionResult(
                output=draft.output,
                validation=validation,
                reflection=reflection,
                abstained=True,
                error_code="revision_evidence_violation",
                llm_call_ids=tuple(call_ids),
            )
        revised_validation = self._validator.validate(
            node_name=node_name,
            output=revision.output,
            output_schema=output_schema,
        )
        return NodeExecutionResult(
            output=revision.output,
            validation=revised_validation,
            reflection=reflection,
            revision_count=1,
            abstained=not revised_validation.valid,
            error_code=(
                None
                if revised_validation.valid
                else "deterministic_validation_failed"
            ),
            llm_call_ids=tuple(call_ids),
        )

    def _call(self, **kwargs: Any) -> StructuredLLMResponse:
        """call."""
        return self._llm.complete_structured(**kwargs)


def _derive_prompt(
    prompt: RenderedPrompt,
    *,
    kind: str,
    draft: dict[str, Any],
    reflection: dict[str, Any] | None = None,
) -> RenderedPrompt:
    """Create an explicit critic/revision prompt without changing safety order."""
    sections = list(prompt.sections)
    sections.append(
        PromptSection(
            title="CURRENT DRAFT",
            content=_render_json(draft),
        )
    )
    if reflection is not None:
        sections.append(
            PromptSection(
                title="CRITIC FINDINGS",
                content=_render_json(reflection),
            )
        )
    task = (
        "Critique the current draft. Return only the reflection schema and do "
        "not add evidence or facts."
        if kind == "reflection"
        else "Revise the draft once using only existing evidence IDs and the critic findings."
    )
    sections.append(PromptSection(title="CURRENT NODE TASK", content=task))
    return RenderedPrompt(
        node_name=prompt.node_name,
        kind=kind,
        prompt_version=f"{prompt.prompt_version.rsplit(':', 1)[0]}:{kind}",
        sections=tuple(sections),
    )


def _render_json(value: dict[str, Any]) -> str:
    """Render structured node state deterministically."""
    import json

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
