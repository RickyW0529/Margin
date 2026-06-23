"""Candidate selector for quant output."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from margin.valuation_discovery.models import QuantResult, ResearchGuardrail, ScreeningStatus


@dataclass(frozen=True)
class SelectorConfig:
    """Configurable candidate selector parameters."""

    top_n: int = 50
    min_score: float = 70.0
    allowed_statuses: tuple[ScreeningStatus, ...] = (
        ScreeningStatus.PASS,
        ScreeningStatus.NEAR_THRESHOLD,
    )
    excluded_guardrails: tuple[ResearchGuardrail, ...] = (
        ResearchGuardrail.RESEARCH_BLOCKED,
    )


class MultiFactorSelector:
    """Select research candidates from quant results."""

    def __init__(self, config: SelectorConfig) -> None:
        """init  ."""
        self._config = config

    def select(self, results: Iterable[QuantResult]) -> tuple[QuantResult, ...]:
        """Return sorted quant candidates eligible for research/news refresh."""
        filtered = [
            result
            for result in results
            if result.screening_status in self._config.allowed_statuses
            and result.research_guardrail not in self._config.excluded_guardrails
            and result.final_score >= self._config.min_score
        ]
        filtered.sort(key=lambda item: item.final_score, reverse=True)
        return tuple(filtered[: self._config.top_n])
