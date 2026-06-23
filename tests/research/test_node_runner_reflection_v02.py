"""v0.2 node runner and bounded reflection tests."""

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
    """runner always runs deterministic validation."""
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
    """forced critic allows one revision."""
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
    """needs evidence does not allow critic to add facts."""
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
    """critic cannot replace evidence ids."""
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
    """An LLM critic cannot waive deterministic schema/evidence validation."""
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
    """llm service records hash only audit metadata."""
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
    """FakeLLM."""
    def __init__(self, outputs: list[dict]) -> None:
        """Initialize the instance."""
        self.outputs = list(outputs)
        self.call_count = 0

    def complete_structured(self, **kwargs) -> StructuredLLMResponse:
        """complete structured."""
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
    """FakeValidator."""
    def __init__(self, *, valid: bool = True) -> None:
        """Initialize the instance."""
        self.valid = valid
        self.calls = 0

    def validate(self, *, node_name, output, output_schema) -> DeterministicValidation:
        """validate."""
        del node_name, output, output_schema
        self.calls += 1
        return DeterministicValidation(
            valid=self.valid,
            issues=() if self.valid else ("invalid",),
        )


def _prompt() -> RenderedPrompt:
    """prompt."""
    return RenderedPrompt(
        node_name="test",
        kind="draft",
        prompt_version="prompt-v0.2.0:draft",
        sections=(PromptSection(title="SYSTEM SAFETY", content="safe"),),
    )
