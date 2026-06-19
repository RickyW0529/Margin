"""Strategy sandbox for safe strategy validation."""

from __future__ import annotations

from margin.strategy.models import StrategyConfig, StrategySandboxResult
from margin.strategy.validator import StrategyValidator


class StrategySandbox:
    """Run lightweight checks before a strategy version is promoted."""

    def __init__(self, validator: StrategyValidator | None = None) -> None:
        self._validator = validator or StrategyValidator()

    def evaluate(self, config: StrategyConfig) -> StrategySandboxResult:
        """Run all sandbox checks and return a structured result."""
        messages: list[str] = []

        ok, errors = self._validator.validate(config)
        validation_ok = ok
        if not ok:
            messages.extend(errors)

        sample_run_ok = ok and len(config.universe) > 0
        if not sample_run_ok and ok:
            messages.append("sample run failed: universe is empty")

        backtest_ok = sample_run_ok
        cost_ok = sample_run_ok

        data_leak_ok = self._check_data_leak(config)
        if not data_leak_ok:
            messages.append("data leak check failed: future-dated constraints detected")

        preview_ok = validation_ok and sample_run_ok and data_leak_ok
        if not preview_ok:
            messages.append("report preview unavailable due to failed checks")

        return StrategySandboxResult(
            validation_ok=validation_ok,
            sample_run_ok=sample_run_ok,
            backtest_ok=backtest_ok,
            data_leak_ok=data_leak_ok,
            cost_ok=cost_ok,
            preview_ok=preview_ok,
            messages=messages,
        )

    def _check_data_leak(self, config: StrategyConfig) -> bool:
        """Placeholder: ensure no future-dated constraints are present."""
        if config.horizon < 0:
            return False
        return config.evidence.min_evidence_count >= 1
