"""Deterministic ContextFact ranker."""

from __future__ import annotations

from margin.agents.protocol.models import ContextFact

_FACT_PRIORITY = {
    "risk_flag": 100,
    "data_status": 90,
    "evidence_claim": 80,
    "quant_signal": 70,
    "metric": 50,
    "open_question": 40,
    "user_constraint": 30,
    "decision": 20,
}


class ContextFactRanker:
    """ContextFactRanker.."""

    def rank(self, facts: tuple[ContextFact, ...]) -> tuple[ContextFact, ...]:
        """Rank.

        Args:
            facts: tuple[ContextFact, ...]: .

        Returns:
            tuple[ContextFact, ...]: .
        """
        return tuple(
            sorted(
                facts,
                key=lambda fact: (
                    _FACT_PRIORITY.get(str(fact.fact_type), 0),
                    fact.confidence,
                    fact.fact_id,
                ),
                reverse=True,
            )
        )
