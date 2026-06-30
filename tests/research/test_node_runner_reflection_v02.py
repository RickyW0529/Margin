"""v0.2 node runner and bounded reflection tests.

This module verifies that the node execution runner always runs deterministic
validation, that forced critic reflection allows at most one revision, that
``needs_evidence`` actions do not let the critic add facts, that the critic
cannot replace evidence IDs, that an LLM accept cannot override failed
deterministic validation, and that the LLM service records hash-only audit
metadata.
"""

from __future__ import annotations

from margin.research.execution.llm_service import (
    LLMService,
    MemoryLLMCallAuditRepository,
    StructuredLLMResponse,
)
from margin.research.execution.node_runner import (
    DeterministicValidation,
    NodeExecutionRunner,
)
from margin.research.execution.reflection import ReflectionAction
from margin.research.llm import DeterministicLLMProvider
from margin.research.prompts.models import PromptSection, RenderedPrompt


def test_runner_always_runs_deterministic_validation() -> None:
    """Verify the runner always runs deterministic validation before accepting output.

    Runs an LLM node with a conditional reflection policy and asserts that the
    validator is called once, the output is returned, and only one LLM call
    was made.
    """
    llm = FakeLLM([{"analysis": "ok", "evidence_ids": ["ev-1"]}])
    validator = FakeValidator()
    runner = NodeExecutionRunner(llm=llm, validator=validator)

    result = runner.run_llm_node(
        graph_run_id="graph-1",
        node_name="fundamental_analysis",
        prompt=_prompt(),
        output_schema={"type": "object"},
        reflection_policy="conditional",
    )

    assert validator.calls == 1
    assert result.output["analysis"] == "ok"
    assert llm.call_count == 1


def test_forced_critic_allows_one_revision() -> None:
    """Verify forced critic reflection allows exactly one revision.

    Runs an LLM node with a forced reflection policy where the critic requests
    a revision, and asserts that the reflection action is ``REVISE``, one
    revision was made, the revised output is returned, and three LLM calls
    were made (draft, critic, revision).
    """
    llm = FakeLLM(
        [
            {"analysis": "draft", "evidence_ids": ["ev-1"]},
            {
                "action": "revise",
                "reasons": ["overstated"],
                "evidence_ids": ["ev-1"],
            },
            {"analysis": "revised", "evidence_ids": ["ev-1"]},
        ]
    )
    validator = FakeValidator()
    runner = NodeExecutionRunner(llm=llm, validator=validator)

    result = runner.run_llm_node(
        graph_run_id="graph-1",
        node_name="delta_decision",
        prompt=_prompt(),
        output_schema={"type": "object"},
        reflection_policy="forced",
    )

    assert result.reflection is not None
    assert result.reflection.action == ReflectionAction.REVISE
    assert result.revision_count == 1
    assert result.output["analysis"] == "revised"
    assert llm.call_count == 3
    assert validator.calls == 2


def test_needs_evidence_does_not_allow_critic_to_add_facts() -> None:
    """Verify a ``needs_evidence`` critic action does not allow adding facts.

    Runs an LLM node where the critic requests evidence and asserts that an
    evidence gap is requested, no revision is made, and exactly two LLM calls
    occur (draft and critic).
    """
    llm = FakeLLM(
        [
            {"analysis": "draft", "evidence_ids": ["ev-1"]},
            {
                "action": "needs_evidence",
                "reasons": ["missing cash-flow evidence"],
                "evidence_ids": ["ev-1"],
            },
        ]
    )
    runner = NodeExecutionRunner(llm=llm, validator=FakeValidator())

    result = runner.run_llm_node(
        graph_run_id="graph-1",
        node_name="risk_review",
        prompt=_prompt(),
        output_schema={"type": "object"},
        reflection_policy="forced",
    )

    assert result.evidence_gap_requested is True
    assert result.revision_count == 0
    assert llm.call_count == 2


def test_critic_cannot_replace_evidence_ids() -> None:
    """Verify the critic cannot replace evidence IDs with invented ones.

    Runs an LLM node where the critic attempts to revise with a different
    evidence ID and asserts that the runner abstains with a
    ``reflection_evidence_violation`` error code and no revisions are made.
    """
    llm = FakeLLM(
        [
            {"analysis": "draft", "evidence_ids": ["ev-1"]},
            {
                "action": "revise",
                "reasons": ["use another source"],
                "evidence_ids": ["ev-invented"],
            },
        ]
    )
    runner = NodeExecutionRunner(llm=llm, validator=FakeValidator())

    result = runner.run_llm_node(
        graph_run_id="graph-1",
        node_name="delta_decision",
        prompt=_prompt(),
        output_schema={"type": "object"},
        reflection_policy="forced",
    )

    assert result.abstained is True
    assert result.error_code == "reflection_evidence_violation"
    assert result.revision_count == 0


def test_critic_accept_cannot_override_failed_deterministic_validation() -> None:
    """Verify an LLM critic cannot waive deterministic schema/evidence validation.

    Runs an LLM node where the deterministic validator fails and the critic
    accepts, and asserts that the runner abstains with a
    ``deterministic_validation_failed`` error code.
    """
    llm = FakeLLM(
        [
            {"analysis": "draft", "evidence_ids": ["ev-invented"]},
            {
                "action": "accept",
                "reasons": ["looks plausible"],
                "evidence_ids": ["ev-invented"],
            },
        ]
    )
    runner = NodeExecutionRunner(llm=llm, validator=FakeValidator(valid=False))

    result = runner.run_llm_node(
        graph_run_id="graph-1",
        node_name="fundamental_analysis",
        prompt=_prompt(),
        output_schema={"type": "object"},
        reflection_policy="conditional",
    )

    assert result.abstained is True
    assert result.error_code == "deterministic_validation_failed"


def test_llm_service_records_hash_only_audit_metadata() -> None:
    """Verify the LLM service records hash-only audit metadata.

    Runs a structured completion through the LLM service and asserts that the
    audit record contains SHA-256 prompt and schema hashes, the correct model
    name, and does not expose raw prompt or response text.
    """
    audit = MemoryLLMCallAuditRepository()
    service = LLMService(
        DeterministicLLMProvider(response={"analysis": "ok"}),
        audit_repository=audit,
    )

    result = service.complete_structured(
        prompt=_prompt(),
        output_schema={
            "type": "object",
            "properties": {"analysis": {"type": "string"}},
            "required": ["analysis"],
        },
        task_type="draft",
        node_name="fundamental_analysis",
        graph_run_id="graph-1",
    )

    assert result.success is True
    [record] = audit.records
    assert record.prompt_hash.startswith("sha256:")
    assert record.schema_hash.startswith("sha256:")
    assert record.model == "deterministic_llm"
    assert "prompt" not in record.model_dump()
    assert "response" not in record.model_dump()


class FakeLLM:
    """Fake LLM service that returns pre-configured outputs in sequence.

    Attributes:
        outputs: List of output dictionaries to return in order.
        call_count: Number of times ``complete_structured`` was called.
    """

    def __init__(self, outputs: list[dict]) -> None:
        """Initialize the fake LLM with a queue of outputs.

        Args:
            outputs: List of output dictionaries to return in sequence.
        """
        self.outputs = list(outputs)
        self.call_count = 0

    def complete_structured(self, **kwargs) -> StructuredLLMResponse:
        """Return the next pre-configured output and increment the call counter.

        Args:
            **kwargs: Keyword arguments including ``task_type``.

        Returns:
            A ``StructuredLLMResponse`` with the next queued output.
        """
        self.call_count += 1
        output = self.outputs.pop(0)
        return StructuredLLMResponse(
            call_id=f"llm-{self.call_count}",
            output=output,
            model="fake-model",
            success=True,
            latency_ms=0.0,
            task_type=str(kwargs["task_type"]),
        )


class FakeValidator:
    """Fake deterministic validator that returns a configurable validation result.

    Attributes:
        valid: Whether the validation should pass.
        calls: Number of times ``validate`` was called.
    """

    def __init__(self, *, valid: bool = True) -> None:
        """Initialize the fake validator with a pass/fail configuration.

        Args:
            valid: Whether validation should pass.
        """
        self.valid = valid
        self.calls = 0

    def validate(self, *, node_name, output, output_schema) -> DeterministicValidation:
        """Return a deterministic validation result and increment the call counter.

        Args:
            node_name: The name of the node being validated.
            output: The output to validate.
            output_schema: The JSON schema to validate against.

        Returns:
            A ``DeterministicValidation`` with the configured validity.
        """
        del node_name, output, output_schema
        self.calls += 1
        return DeterministicValidation(
            valid=self.valid,
            issues=() if self.valid else ("invalid",),
        )


def _prompt() -> RenderedPrompt:
    """Build a minimal rendered prompt for use in node runner tests."""
    return RenderedPrompt(
        node_name="test",
        kind="draft",
        prompt_version="prompt-v0.2.0:draft",
        sections=(PromptSection(title="SYSTEM SAFETY", content="safe"),),
    )
