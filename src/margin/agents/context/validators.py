"""Context safety validators."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

_UNSAFE_TEXT_MARKERS = (
    "raw_text",
    "provider_token",
    "api_key",
    "authorization",
    "password",
    "secret-token",
    "system_prompt",
)


@dataclass(frozen=True)
class ContextValidationResult:
    """ContextValidationResult.."""

    valid: bool
    problems: tuple[str, ...] = ()


class NoRawPayloadValidator:
    """NoRawPayloadValidator.."""

    def validate(self, model: BaseModel) -> ContextValidationResult:
        """Validate.

        Args:
            model: BaseModel: .

        Returns:
            ContextValidationResult: .
        """
        payload = model.model_dump_json().lower()
        problems = tuple(marker for marker in ("raw_text", "raw payload") if marker in payload)
        return ContextValidationResult(valid=not problems, problems=problems)


class SecretRedactionValidator:
    """SecretRedactionValidator.."""

    def validate(self, model: BaseModel) -> ContextValidationResult:
        """Validate.

        Args:
            model: BaseModel: .

        Returns:
            ContextValidationResult: .
        """
        payload = model.model_dump_json().lower()
        problems = tuple(marker for marker in _UNSAFE_TEXT_MARKERS if marker in payload)
        return ContextValidationResult(valid=not problems, problems=problems)
