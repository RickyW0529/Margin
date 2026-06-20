"""Strategy configuration validation and guardrail merging."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from margin.strategy.models import StrategyConfig


class StrategyValidator:
    """Validate user strategy configs and merge with system guardrails."""

    def validate(self, config: StrategyConfig) -> tuple[bool, list[str]]:
        """Return validation status and a list of guardrail errors.

        Pydantic-level validation is already handled by the model. This method
        adds guardrail checks that the user cannot disable, such as ensuring
        the universe is non-empty and the investment horizon is positive.

        Args:
            config: The strategy configuration to validate.

        Returns:
            A tuple ``(ok, errors)`` where ``ok`` is ``True`` when no guardrail
            errors are found and ``errors`` is a list of human-readable
            violation messages.
        """
        errors: list[str] = []

        try:
            config.model_validate(config.model_dump())
        except ValidationError as exc:
            for err in exc.errors():
                errors.append(f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}")

        if not config.universe:
            errors.append("universe must not be empty")

        if config.evidence.min_evidence_count < 1:
            errors.append("evidence.min_evidence_count must be at least 1")

        if config.horizon < 1:
            errors.append("horizon must be positive")

        if not 0.0 < config.risk.max_position_weight <= 1.0:
            errors.append("risk.max_position_weight must be in (0, 1]")

        return len(errors) == 0, errors

    def merge_with_guardrails(self, config: StrategyConfig) -> StrategyConfig:
        """Return a config with system guardrails applied on top.

        The returned config always includes the mandatory prohibited outputs
        and keeps the user's other choices.

        Args:
            config: The user-provided strategy configuration.

        Returns:
            A new :class:`StrategyConfig` with system-level prohibited outputs
            merged into ``decision.prohibited_outputs`` and a minimum evidence
            count of at least one.
        """
        data = config.model_dump()
        decision_data = data.get("decision", {})
        user_prohibited = set(decision_data.get("prohibited_outputs", []))
        system_prohibited = {"GUARANTEED_RETURN", "DIRECT_BUY_SELL_ORDER"}
        decision_data["prohibited_outputs"] = sorted(user_prohibited | system_prohibited)
        data["decision"] = decision_data

        if data.get("evidence", {}).get("min_evidence_count", 0) < 1:
            data.setdefault("evidence", {})["min_evidence_count"] = 1

        return StrategyConfig.model_validate(data)

    def validate_dict(self, data: dict[str, Any]) -> tuple[bool, list[str]]:
        """Validate a raw dictionary and return normalized config if valid.

        Args:
            data: A plain dictionary representing a strategy configuration.

        Returns:
            A tuple ``(ok, errors)``. ``ok`` is ``True`` when ``data`` can be
            parsed into a :class:`StrategyConfig` and passes all guardrail
            checks; otherwise ``errors`` contains the violation messages.
        """
        try:
            config = StrategyConfig.model_validate(data)
        except ValidationError as exc:
            errors = [
                f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}"
                for err in exc.errors()
            ]
            return False, errors
        return self.validate(config)
