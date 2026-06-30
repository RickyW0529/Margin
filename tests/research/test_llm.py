"""Tests for research LLM provider and router.

This module verifies that the deterministic LLM provider returns injected
outputs and can simulate failures, that the real LLM provider defaults to
the expected model, that the model router selects task-specific models with
fallback, that the structured output guardrail validates required fields,
and that the LLM healthcheck correctly reports healthy and unhealthy states.
"""

from __future__ import annotations

from margin.core.provider import ProviderStatus
from margin.research.llm import DeterministicLLMProvider, LLMProvider, ModelRouter, TaskType


class _FakeResponse:
    """Fake HTTP response object for testing the LLM provider.

    Attributes:
        status_code: The HTTP status code of the response.
    """

    def __init__(self, payload: dict, status_code: int = 200) -> None:
        """Initialize the fake response with a payload and status code.

        Args:
            payload: The dictionary returned by ``json()``.
            status_code: The HTTP status code to simulate.
        """
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        """Raise a ``RuntimeError`` if the status code indicates an error."""
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict:
        """Return the injected payload dictionary."""
        return self._payload


class _FakeClient:
    """Fake HTTP client that records calls and returns a canned response.

    Attributes:
        response: The response or exception to return on ``post``.
        calls: List of recorded call arguments.
    """

    def __init__(self, response: _FakeResponse | Exception) -> None:
        """Initialize the fake client with a response or exception.

        Args:
            response: A ``_FakeResponse`` to return or an ``Exception`` to
                raise on the next ``post`` call.
        """
        self.response = response
        self.calls: list[dict] = []

    def post(self, *args, **kwargs):
        """Record the call and return the injected response or raise an exception."""
        self.calls.append({"args": args, "kwargs": kwargs})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_deterministic_provider_returns_injected_output():
    """Verify the deterministic LLM provider returns the injected output."""
    provider = DeterministicLLMProvider(name="mock", response={"answer": "ok"})
    result = provider.complete("hi", response_schema={"answer": {"type": "string"}})
    assert result.output == {"answer": "ok"}
    assert result.success is True


def test_deterministic_provider_can_fail():
    """Verify the deterministic LLM provider can simulate a failure."""
    provider = DeterministicLLMProvider(fail=True, error="injected failure")
    result = provider.complete("hi")
    assert result.success is False
    assert result.error == "injected failure"


def test_llm_provider_direct_default_model_is_deepseek_pro(monkeypatch):
    """Verify the LLM provider defaults to the deepseek-pro model.

    Args:
        monkeypatch: Pytest fixture for temporarily modifying environment
            variables.
    """
    monkeypatch.delenv("MARGIN_LLM_MODEL", raising=False)
    provider = LLMProvider(api_key=None, base_url=None)

    assert provider.descriptor.version == "deepseek-v4-pro"


def test_model_router_selects_cheap_model_for_extraction():
    """Verify the model router selects a task-specific model for extraction."""
    router = ModelRouter({TaskType.EXTRACTION: "cheap-model"})
    model = router.select(TaskType.EXTRACTION)
    assert model == "cheap-model"


def test_model_router_falls_back_to_default():
    """Verify the model router falls back to the default model for unregistered tasks."""
    router = ModelRouter()
    assert router.select(TaskType.REFLECT) == "capable-llm"


def test_guardrail_validates_required_fields():
    """Verify the structured output guardrail rejects missing required fields."""
    from margin.research.llm import StructuredOutputGuardrail

    guardrail = StructuredOutputGuardrail({"required": ["x"]})
    ok, msg = guardrail.validate({})
    assert ok is False
    assert "missing" in msg


def test_model_router_uses_registered_fallback_provider():
    """Verify the model router uses a registered fallback provider on primary failure.

    Configures a primary provider that always fails and a fallback provider
    that succeeds, then asserts that the router completes the task using the
    fallback model.
    """
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


def test_llm_healthcheck_performs_real_completion_request():
    """Verify the LLM healthcheck performs a real completion request.

    Uses a fake HTTP client returning a valid chat completion response and
    asserts that the healthcheck reports a healthy status, the provider name
    is ``openai_llm``, and the request was sent to the correct endpoint.
    """
    client = _FakeClient(
        _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": '{"ok": true}',
                        },
                    }
                ]
            }
        )
    )
    provider = LLMProvider(
        api_key="test-key",
        base_url="https://llm.example.com",
        model="deepseek-v4-flash",
        client=client,
    )

    health = provider.healthcheck()

    assert health.status == ProviderStatus.HEALTHY
    assert health.provider_name == "openai_llm"
    assert client.calls
    assert client.calls[0]["args"][0] == "https://llm.example.com/chat/completions"


def test_llm_healthcheck_reports_unhealthy_when_completion_fails():
    """Verify the LLM healthcheck reports unhealthy when the completion fails.

    Uses a fake HTTP client that raises a network error and asserts that the
    healthcheck reports an unhealthy status with the error message.
    """
    provider = LLMProvider(
        api_key="test-key",
        base_url="https://llm.example.com",
        model="deepseek-v4-flash",
        client=_FakeClient(RuntimeError("network down")),
    )

    health = provider.healthcheck()

    assert health.status == ProviderStatus.UNHEALTHY
    assert "network down" in (health.message or "")
