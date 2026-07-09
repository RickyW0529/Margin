"""LLM provider adapter, model router, and structured-output guardrail."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

import httpx

from margin.core.provider import (
    BaseProvider,
    HealthCheckResult,
    ProviderDescriptor,
    ProviderStatus,
    ProviderType,
)
from margin.core.registry import ProviderNotFoundError, ProviderRegistry
from margin.core.resilience import ProviderError
from margin.news.models import utc_now

_LEADING_THINK_BLOCK_RE = re.compile(r"^\s*<think>.*?</think>\s*", re.DOTALL | re.I)


class TaskType(StrEnum):
    """Research task types used for routing.."""

    UNIVERSE_FILTER = "universe_filter"
    QUANT = "quant"
    WEBSEARCH = "websearch"
    SUMMARY = "summary"
    EVIDENCE = "evidence"
    VALUATION = "valuation"
    RISK = "risk"
    REFLECT = "reflect"
    SIGNAL = "signal"
    EXTRACTION = "extraction"
    VALIDATION = "validation"


@dataclass(frozen=True)
class LLMResult:
    """Result of an LLM completion call.."""

    output: dict[str, Any]
    model: str
    success: bool
    latency_ms: float
    error: str | None = None
    raw_response: str | None = None


def _compute_hash(data: Any) -> str:
    """Return a deterministic SHA-256 hash for the supplied data.

    Args:
        data: Any: .

    Returns:
        str: .
    """
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def parse_structured_content(content: str) -> dict[str, Any]:
    """Parse JSON content, tolerating model reasoning preambles.

    Args:
        content: str: Raw model response content.

    Returns:
        dict[str, Any]: Parsed JSON object.
    """
    stripped = strip_thinking_blocks(content)
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        parsed = json.JSONDecoder().raw_decode(_structured_json_candidate(stripped))[0]
    if not isinstance(parsed, dict):
        raise ValueError("structured LLM response must be a JSON object")
    return parsed


def _structured_json_candidate(content: str) -> str:
    """Return the most likely JSON suffix from a model response.

    Args:
        content: str: Raw model response content.

    Returns:
        str: Candidate string starting with JSON object or array syntax.
    """
    content = strip_thinking_blocks(content)
    object_index = content.find("{")
    array_index = content.find("[")
    indexes = [index for index in (object_index, array_index) if index >= 0]
    if not indexes:
        return content
    return content[min(indexes) :]


def strip_thinking_blocks(content: str) -> str:
    """Remove leading model reasoning blocks from user-visible output.

    Args:
        content: str: Raw model response content.

    Returns:
        str: Content without a leading ``<think>...</think>`` block.
    """
    return _LEADING_THINK_BLOCK_RE.sub("", content).strip()


class LLMProvider(BaseProvider):
    """OpenAI-compatible LLM provider with structured JSON output.."""

    def __init__(
        self,
        name: str = "openai_llm",
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        client: httpx.Client | None = None,
        timeout: float = 60.0,
    ) -> None:
        """Initialize the provider.

        Args:
            name: str: .
            api_key: str | None: .
            base_url: str | None: .
            model: str | None: .
            client: httpx.Client | None: .
            timeout: float: .

        Returns:
            None: .
        """
        self._api_key = api_key
        self._base_url = (base_url or "").rstrip("/")
        self._model = model or "deepseek-v4-pro"
        self._timeout = timeout
        self._client = client or httpx.Client()
        self._descriptor = ProviderDescriptor(
            name=name,
            version=self._model,
            provider_type=ProviderType.LLM,
            capabilities=["complete", "complete_structured"],
            secret_refs=["llm_api_key"],
            config={"base_url": self._base_url, "model": self._model},
        )

    @property
    def descriptor(self) -> ProviderDescriptor:
        """Return the provider descriptor for registry integration.

        Returns:
            ProviderDescriptor: .
        """
        return self._descriptor

    def complete(
        self,
        prompt: str,
        *,
        response_schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
    ) -> LLMResult:
        """Call the LLM with an optional structured JSON schema.

        Args:
            prompt: str: .
            response_schema: dict[str, Any] | None: .
            temperature: float: .

        Returns:
            LLMResult: .
        """
        if not self._api_key or not self._base_url:
            return LLMResult(
                output={},
                model=self._model,
                success=False,
                latency_ms=0.0,
                error="LLM API key or base URL not configured",
            )

        start = datetime.now().timestamp()
        messages = [{"role": "user", "content": prompt}]
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
        }
        if response_schema is not None:
            payload["response_format"] = {"type": "json_object"}
            payload["messages"].insert(
                0,
                {
                    "role": "system",
                    "content": (
                        "Respond with valid JSON matching this schema: "
                        f"{json.dumps(response_schema)}"
                    ),
                },
            )

        try:
            response = self._client.post(
                f"{self._base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self._timeout,
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            output = parse_structured_content(content) if response_schema else {"content": content}
            latency = (datetime.now().timestamp() - start) * 1000
            return LLMResult(
                output=output,
                model=self._model,
                success=True,
                latency_ms=latency,
                raw_response=content,
            )
        except Exception as exc:
            latency = (datetime.now().timestamp() - start) * 1000
            return LLMResult(
                output={},
                model=self._model,
                success=False,
                latency_ms=latency,
                error=f"{type(exc).__name__}: {exc}",
            )

    def complete_or_raise(
        self,
        prompt: str,
        *,
        response_schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
    ) -> LLMResult:
        """Registry-compatible completion that raises on Provider failure.

        Args:
            prompt: str: .
            response_schema: dict[str, Any] | None: .
            temperature: float: .

        Returns:
            LLMResult: .
        """
        result = self.complete(
            prompt,
            response_schema=response_schema,
            temperature=temperature,
        )
        if not result.success:
            raise ProviderError(result.error or "LLM completion failed")
        return result

    def configure_secrets(self, secrets: dict[str, str]) -> None:
        """Receive the LLM API key from :class:`ProviderRegistry`.

        Args:
            secrets: dict[str, str]: .

        Returns:
            None: .
        """
        api_key = secrets.get("llm_api_key")
        if api_key:
            self._api_key = api_key

    def healthcheck(self) -> HealthCheckResult:
        """Check connectivity and credentials.

        Returns:
            HealthCheckResult: .
        """
        if not self._api_key or not self._base_url:
            return HealthCheckResult(
                provider_name=self._descriptor.name,
                status=ProviderStatus.DEGRADED,
                checked_at=utc_now(),
                message="LLM not configured",
            )
        result = self.complete(
            'Return JSON only: {"ok": true}',
            response_schema={
                "type": "object",
                "properties": {"ok": {"type": "boolean"}},
                "required": ["ok"],
            },
            temperature=0.0,
        )
        if not result.success:
            return HealthCheckResult(
                provider_name=self._descriptor.name,
                status=ProviderStatus.UNHEALTHY,
                checked_at=utc_now(),
                latency_ms=result.latency_ms,
                message=result.error or "LLM healthcheck failed",
                details={"model": self._model},
            )
        return HealthCheckResult(
            provider_name=self._descriptor.name,
            status=ProviderStatus.HEALTHY,
            checked_at=utc_now(),
            latency_ms=result.latency_ms,
            details={"model": self._model},
        )


class DeterministicLLMProvider(LLMProvider):
    """Test double that ignores prompts and returns a fixed JSON object.."""

    def __init__(
        self,
        name: str = "deterministic_llm",
        response: dict[str, Any] | None = None,
        fail: bool = False,
        error: str = "injected failure",
    ) -> None:
        """Initialize the deterministic test provider.

        Args:
            name: str: .
            response: dict[str, Any] | None: .
            fail: bool: .
            error: str: .

        Returns:
            None: .
        """
        self._response = response or {"result": "ok"}
        self._fail = fail
        self._error = error
        self._descriptor = ProviderDescriptor(
            name=name,
            version="test",
            provider_type=ProviderType.LLM,
            capabilities=["complete", "complete_structured"],
            config={"mode": "deterministic"},
        )

    @property
    def descriptor(self) -> ProviderDescriptor:
        """Return the provider descriptor.

        Returns:
            ProviderDescriptor: .
        """
        return self._descriptor

    def complete(
        self,
        prompt: str,
        *,
        response_schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
    ) -> LLMResult:
        """Return the configured deterministic response.

        Args:
            prompt: str: .
            response_schema: dict[str, Any] | None: .
            temperature: float: .

        Returns:
            LLMResult: .
        """
        del prompt, response_schema, temperature
        if self._fail:
            return LLMResult(
                output={},
                model=self._descriptor.name,
                success=False,
                latency_ms=0.0,
                error=self._error,
            )
        return LLMResult(
            output=dict(self._response),
            model=self._descriptor.name,
            success=True,
            latency_ms=0.0,
            raw_response=json.dumps(self._response),
        )

    def healthcheck(self) -> HealthCheckResult:
        """Always report healthy.

        Returns:
            HealthCheckResult: .
        """
        return HealthCheckResult(
            provider_name=self._descriptor.name,
            status=ProviderStatus.HEALTHY,
            checked_at=utc_now(),
        )


class ModelRouter:
    """Route research tasks to model/tool/budget/schema configurations.."""

    DEFAULTS: dict[TaskType, str] = {
        TaskType.UNIVERSE_FILTER: "rule",
        TaskType.QUANT: "rule",
        TaskType.WEBSEARCH: "rule",
        TaskType.SUMMARY: "cheap-llm",
        TaskType.EVIDENCE: "cheap-llm",
        TaskType.VALUATION: "rule",
        TaskType.RISK: "cheap-llm",
        TaskType.REFLECT: "capable-llm",
        TaskType.SIGNAL: "cheap-llm",
        TaskType.EXTRACTION: "cheap-llm",
        TaskType.VALIDATION: "cheap-llm",
    }

    def __init__(
        self,
        overrides: dict[TaskType, str] | None = None,
        llm_providers: dict[str, LLMProvider] | None = None,
        provider_registry: ProviderRegistry | None = None,
    ) -> None:
        """Initialize the router.

        Args:
            overrides: dict[TaskType, str] | None: .
            llm_providers: dict[str, LLMProvider] | None: .
            provider_registry: ProviderRegistry | None: .

        Returns:
            None: .
        """
        self._mapping = dict(self.DEFAULTS)
        if overrides:
            self._mapping.update(overrides)
        self._registry = provider_registry or ProviderRegistry()
        self._providers: dict[str, LLMProvider] = {}
        for name, provider in (llm_providers or {}).items():
            self.register_provider(name, provider)

    def select(self, task: TaskType) -> str:
        """Return the provider name selected for a task.

        Args:
            task: TaskType: .

        Returns:
            str: .
        """
        return self._mapping.get(task, "rule")

    def get_provider(self, name: str) -> LLMProvider | None:
        """Return a registered provider by name.

        Args:
            name: str: .

        Returns:
            LLMProvider | None: .
        """
        return self._providers.get(name)

    def register_provider(
        self,
        name: str,
        provider: LLMProvider,
        *,
        fallback_names: list[str] | None = None,
    ) -> None:
        """Register a named provider with the shared registry.

        Args:
            name: str: .
            provider: LLMProvider: .
            fallback_names: list[str] | None: .

        Returns:
            None: .
        """
        self._providers[name] = provider
        self._registry.register(
            provider,
            fallback_names=fallback_names,
            allow_override=True,
        )

    def complete(
        self,
        task: TaskType,
        prompt: str,
        *,
        response_schema: dict[str, Any] | None = None,
        trace_id: str = "",
    ) -> LLMResult:
        """Route a completion through the shared Provider Registry.

        Args:
            task: TaskType: .
            prompt: str: .
            response_schema: dict[str, Any] | None: .
            trace_id: str: .

        Returns:
            LLMResult: .
        """
        provider_name = self.select(task)
        if provider_name == "rule":
            return LLMResult(
                output={},
                model="rule",
                success=False,
                latency_ms=0.0,
                error=f"task '{task}' is configured for rule execution",
            )
        try:
            data, call = self._registry.call(
                provider_name,
                "complete_or_raise",
                kwargs={
                    "prompt": prompt,
                    "response_schema": response_schema,
                },
                trace_id=trace_id,
            )
        except (ProviderError, ProviderNotFoundError) as exc:
            return LLMResult(
                output={},
                model=provider_name,
                success=False,
                latency_ms=0.0,
                error=f"{type(exc).__name__}: {exc}",
            )
        if not call.success or not isinstance(data, LLMResult):
            return LLMResult(
                output={},
                model=call.provider_name,
                success=False,
                latency_ms=call.latency_ms or 0.0,
                error=call.error or "invalid LLM Provider result",
            )
        return data


class StructuredOutputGuardrail:
    """Validate that an LLM output conforms to the supported JSON Schema subset.."""

    def __init__(self, schema: dict[str, Any]) -> None:
        """Initialize the guardrail with a JSON schema.

        Args:
            schema: dict[str, Any]: .

        Returns:
            None: .
        """
        self._schema = schema

    def validate(self, output: dict[str, Any]) -> tuple[bool, str]:
        """Validate ``output`` against the configured schema.

        Args:
            output: dict[str, Any]: .

        Returns:
            tuple[bool, str]: .
        """
        return self._validate_value(output, self._schema, "$")

    def _validate_value(
        self,
        value: Any,
        schema: dict[str, Any],
        path: str,
    ) -> tuple[bool, str]:
        """Recursively validate a value against a schema fragment.

        Args:
            value: Any: .
            schema: dict[str, Any]: .
            path: str: .

        Returns:
            tuple[bool, str]: .
        """
        expected_type = schema.get("type")
        type_checks = {
            "object": lambda candidate: isinstance(candidate, dict),
            "array": lambda candidate: isinstance(candidate, list),
            "string": lambda candidate: isinstance(candidate, str),
            "number": lambda candidate: (
                isinstance(candidate, (int, float)) and not isinstance(candidate, bool)
            ),
            "integer": lambda candidate: (
                isinstance(candidate, int) and not isinstance(candidate, bool)
            ),
            "boolean": lambda candidate: isinstance(candidate, bool),
            "null": lambda candidate: candidate is None,
        }
        if expected_type in type_checks and not type_checks[expected_type](value):
            return False, f"{path} must be {expected_type}"

        if "enum" in schema and value not in schema["enum"]:
            return False, f"{path} must be one of {schema['enum']}"

        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in schema and value < schema["minimum"]:
                return False, f"{path} must be >= {schema['minimum']}"
            if "maximum" in schema and value > schema["maximum"]:
                return False, f"{path} must be <= {schema['maximum']}"

        if isinstance(value, dict):
            for key in schema.get("required", []):
                if key not in value:
                    return False, f"missing required field: {path}.{key}"
            properties = schema.get("properties", {})
            for key, child in value.items():
                child_schema = properties.get(key)
                if child_schema is None:
                    continue
                valid, message = self._validate_value(
                    child,
                    child_schema,
                    f"{path}.{key}",
                )
                if not valid:
                    return valid, message

        if isinstance(value, list) and "items" in schema:
            for index, item in enumerate(value):
                valid, message = self._validate_value(
                    item,
                    schema["items"],
                    f"{path}[{index}]",
                )
                if not valid:
                    return valid, message

        return True, ""
