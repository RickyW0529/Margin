"""Tests for research LLM provider and router."""

from __future__ import annotations

from margin.research.llm import DeterministicLLMProvider, ModelRouter, TaskType


def test_deterministic_provider_returns_injected_output():
    provider = DeterministicLLMProvider(name="mock", response={"answer": "ok"})
    result = provider.complete("hi", response_schema={"answer": {"type": "string"}})
    assert result.output == {"answer": "ok"}
    assert result.success is True


def test_deterministic_provider_can_fail():
    provider = DeterministicLLMProvider(fail=True, error="injected failure")
    result = provider.complete("hi")
    assert result.success is False
    assert result.error == "injected failure"


def test_model_router_selects_cheap_model_for_extraction():
    router = ModelRouter({TaskType.EXTRACTION: "cheap-model"})
    model = router.select(TaskType.EXTRACTION)
    assert model == "cheap-model"


def test_model_router_falls_back_to_default():
    router = ModelRouter()
    assert router.select(TaskType.REFLECT) == "capable-llm"


def test_guardrail_validates_required_fields():
    from margin.research.llm import StructuredOutputGuardrail

    guardrail = StructuredOutputGuardrail({"required": ["x"]})
    ok, msg = guardrail.validate({})
    assert ok is False
    assert "missing" in msg


def test_model_router_uses_registered_fallback_provider():
    primary = DeterministicLLMProvider(name="primary", fail=True)
    fallback = DeterministicLLMProvider(
        name="fallback",
        response={"risk_score": 0.2},
    )
    router = ModelRouter({TaskType.RISK: "primary"})
    router.register_provider("fallback", fallback)
    router.register_provider("primary", primary, fallback_names=["fallback"])

    result = router.complete(
        TaskType.RISK,
        "review risk",
        response_schema={
            "type": "object",
            "properties": {"risk_score": {"type": "number"}},
            "required": ["risk_score"],
        },
    )

    assert result.success is True
    assert result.model == "fallback"
