"""Context token budget helpers."""

from __future__ import annotations

from margin.agents.protocol.models import ContextFact


def estimate_fact_tokens(fact: ContextFact) -> int:
    """Estimate fact tokens.

    Args:
        fact: ContextFact: .

    Returns:
        int: .
    """
    return max(1, len(fact.statement) // 4)
