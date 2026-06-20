"""Tests for research LLM provider and router."""

from __future__ import annotations

from margin.core.provider import ProviderStatus
from margin.research.llm import DeterministicLLMProvider, LLMProvider, ModelRouter, TaskType


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    def __init__(self, response: _FakeResponse | Exception) -> None:
        self.response = response
        self.calls: list[dict] = []

    def post(self, *args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


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


def test_llm_provider_direct_default_model_is_deepseek_pro(monkeypatch):
    monkeypatch.delenv("MARGIN_LLM_MODEL", raising=False)
    provider = LLMProvider(api_key=None, base_url=None)

    assert provider.descriptor.version == "deepseek-v4-pro"


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


def test_llm_healthcheck_performs_real_completion_request():
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
    provider = LLMProvider(
        api_key="test-key",
        base_url="https://llm.example.com",
        model="deepseek-v4-flash",
        client=_FakeClient(RuntimeError("network down")),
    )

    health = provider.healthcheck()

    assert health.status == ProviderStatus.UNHEALTHY
    assert "network down" in (health.message or "")
