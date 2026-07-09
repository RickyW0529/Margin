"""Strategy configuration validation and guardrail merging."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from margin.strategy.models import (
    ConfigLifecycle,
    ProviderConfigVersion,
    QuantStrategyVersion,
    ResearchScopeVersion,
    StrategyConfig,
    ToolPolicyVersionRef,
    UserStylePromptVersion,
)


class ActivationError(ValueError):
    """Raised when a v0.2 config version cannot be activated safely.."""


class StrategyActivationValidator:
    """Validate v0.2 versioned config lifecycle transitions.."""

    def validate_provider_config_activation(
        self,
        version: ProviderConfigVersion,
    ) -> None:
        """Validate provider config activation without touching secret plaintext.

        Args:
            version: ProviderConfigVersion: .

        Returns:
            None: .
        """
        if not version.enabled:
            raise ActivationError("provider config must be enabled before activation")
        if version.base_url and not (
            version.base_url.startswith("https://")
            or version.base_url.startswith("http://localhost")
            or version.base_url.startswith("http://127.0.0.1")
        ):
            raise ActivationError("provider base_url must be https or local test host")
        if version.lifecycle is ConfigLifecycle.DEPRECATED:
            raise ActivationError("deprecated provider config cannot be activated")

    def validate_quant_strategy_activation(
        self,
        version: QuantStrategyVersion,
    ) -> None:
        """Require calibration evidence before a quant strategy becomes active.

        Args:
            version: QuantStrategyVersion: .

        Returns:
            None: .
        """
        if version.lifecycle is ConfigLifecycle.DEPRECATED:
            raise ActivationError("deprecated quant strategy cannot be activated")
        if not version.calibration_report_id:
            raise ActivationError("quant strategy activation requires a calibration report")

    def validate_style_prompt_activation(
        self,
        version: UserStylePromptVersion,
    ) -> None:
        """Validate user style prompt activation.

        Args:
            version: UserStylePromptVersion: .

        Returns:
            None: .
        """
        if version.lifecycle is ConfigLifecycle.DEPRECATED:
            raise ActivationError("deprecated style prompt cannot be activated")
        if not version.content.strip():
            raise ActivationError("style prompt content must not be empty")
        normalized = version.content.casefold()
        forbidden_phrases = (
            "ignore system",
            "override system",
            "disable pit",
            "bypass tool",
            "disable citation",
            "ignore citation",
            "忽略系统",
            "覆盖系统",
            "关闭pit",
            "禁用pit",
            "绕过工具",
            "取消引用",
            "无需引用",
        )
        if any(phrase in normalized for phrase in forbidden_phrases):
            raise ActivationError("style prompt attempts to override a protected system boundary")

    def validate_tool_policy_activation(
        self,
        version: ToolPolicyVersionRef,
    ) -> None:
        """Reject deprecated or internally contradictory tool policies.

        Args:
            version: ToolPolicyVersionRef: .

        Returns:
            None: .
        """
        if version.lifecycle is ConfigLifecycle.DEPRECATED:
            raise ActivationError("deprecated tool policy cannot be activated")
        overlap = set(version.allowed_tool_names) & set(version.denied_tool_names)
        if overlap:
            raise ActivationError("tool names cannot appear in both allow and deny lists")

    def validate_simple_activation(
        self,
        version: object,
        resource_type: str,
    ) -> None:
        """Reject activation of a deprecated versioned config resource.

        Args:
            version: object: .
            resource_type: str: .

        Returns:
            None: .
        """
        if getattr(version, "lifecycle", None) is ConfigLifecycle.DEPRECATED:
            raise ActivationError(f"deprecated {resource_type} cannot be activated")

    def validate_research_scope_activation(
        self,
        scope: ResearchScopeVersion,
        repository: object,
    ) -> None:
        """Validate that every scope reference exists and points at active config.

        Args:
            scope: ResearchScopeVersion: .
            repository: object: .

        Returns:
            None: .
        """
        if scope.lifecycle is ConfigLifecycle.DEPRECATED:
            raise ActivationError("deprecated research scope cannot be activated")

        self._require_active_reference(
            repository,
            "get_universe_definition",
            scope.universe_version_id,
            "universe definition",
        )
        self._require_active_reference(
            repository,
            "get_indicator_view",
            scope.indicator_view_version_id,
            "indicator view",
        )
        self._require_active_reference(
            repository,
            "get_quant_feature_set",
            scope.quant_feature_set_version_id,
            "quant feature set",
        )
        self._require_active_reference(
            repository,
            "get_quant_strategy",
            scope.quant_strategy_version_id,
            "quant strategy",
        )
        style_prompt = self._require_active_reference(
            repository,
            "get_user_style_prompt",
            scope.ai_prompt_version_id,
            "style prompt",
        )
        tool_policy = self._require_active_reference(
            repository,
            "get_tool_policy",
            scope.tool_policy_version_id,
            "tool policy",
        )
        self.validate_style_prompt_activation(style_prompt)
        self.validate_tool_policy_activation(tool_policy)
        for provider_config_version_id in scope.provider_config_version_ids:
            self._require_active_reference(
                repository,
                "get_provider_config",
                provider_config_version_id,
                "provider config",
            )

    def _require_active_reference(
        self,
        repository: object,
        method_name: str,
        version_id: str,
        resource_type: str,
    ) -> Any:
        """require active reference.

        Args:
            repository: object: .
            method_name: str: .
            version_id: str: .
            resource_type: str: .

        Returns:
            Any: .
        """
        getter = getattr(repository, method_name)
        version = getter(version_id)
        if version is None:
            raise ActivationError(f"missing reference: {resource_type} {version_id}")
        lifecycle = getattr(version, "lifecycle", None)
        if lifecycle is ConfigLifecycle.DEPRECATED:
            raise ActivationError(f"deprecated reference: {resource_type} {version_id}")
        if lifecycle is not ConfigLifecycle.ACTIVE:
            raise ActivationError(f"inactive reference: {resource_type} {version_id}")
        return version


class StrategyValidator:
    """Validate user strategy configs and merge with system guardrails.."""

    def validate(self, config: StrategyConfig) -> tuple[bool, list[str]]:
        """Return validation status and a list of guardrail errors.

        Args:
            config: StrategyConfig: .

        Returns:
            tuple[bool, list[str]]: .
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

        return len(errors) == 0, errors

    def merge_with_guardrails(self, config: StrategyConfig) -> StrategyConfig:
        """Return a config with system guardrails applied on top.

        Args:
            config: StrategyConfig: .

        Returns:
            StrategyConfig: .
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
            data: dict[str, Any]: .

        Returns:
            tuple[bool, list[str]]: .
        """
        try:
            config = StrategyConfig.model_validate(data)
        except ValidationError as exc:
            errors = [
                f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in exc.errors()
            ]
            return False, errors
        return self.validate(config)
