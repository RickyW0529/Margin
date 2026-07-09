"""Strategy version lifecycle state machine."""

from __future__ import annotations

from margin.strategy.models import StrategyState, StrategyVersion


class StrategyLifecycle:
    """Enforce valid state transitions for strategy versions.."""

    _ALLOWED: dict[StrategyState, set[StrategyState]] = {
        StrategyState.DRAFT: {StrategyState.VALIDATING},
        StrategyState.VALIDATING: {
            StrategyState.INVALID,
            StrategyState.BACKTESTING,
        },
        StrategyState.INVALID: set(),
        StrategyState.BACKTESTING: {StrategyState.PAPER_TRADING},
        StrategyState.PAPER_TRADING: {StrategyState.ACTIVE},
        StrategyState.ACTIVE: {StrategyState.ARCHIVED, StrategyState.SUSPENDED},
        StrategyState.SUSPENDED: {StrategyState.ACTIVE, StrategyState.ARCHIVED},
        StrategyState.ARCHIVED: set(),
    }

    def can_transition(self, from_state: StrategyState, to_state: StrategyState) -> bool:
        """Return whether a state transition is allowed.

        Args:
            from_state: StrategyState: .
            to_state: StrategyState: .

        Returns:
            bool: .
        """
        return to_state in self._ALLOWED.get(from_state, set())

    def transition(
        self,
        version: StrategyVersion,
        to_state: StrategyState,
        reason: str = "",
    ) -> StrategyVersion:
        """Return a new version with the updated state.

        Args:
            version: StrategyVersion: .
            to_state: StrategyState: .
            reason: str: .

        Returns:
            StrategyVersion: .
        """
        if not self.can_transition(version.state, to_state):
            raise ValueError(f"cannot transition from {version.state.value} to {to_state.value}")
        description = version.description
        if reason:
            description = f"{description}\nTransition reason: {reason}".strip()
        return version.model_copy(
            update={
                "state": to_state,
                "description": description,
            }
        )
