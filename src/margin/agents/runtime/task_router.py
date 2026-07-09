"""Task routing helpers for v1 Agent runtime."""

from __future__ import annotations

from margin.agents.cards.domain_cards import DomainAgentCard
from margin.agents.cards.worker_cards import WorkerAgentCard
from margin.agents.protocol.models import DomainTaskRequest, WorkerTaskRequest


class TaskRouter:
    """TaskRouter.."""

    def __init__(
        self,
        *,
        domain_cards: tuple[DomainAgentCard, ...] = (),
        worker_cards: tuple[WorkerAgentCard, ...] = (),
    ) -> None:
        """Init .

        Args:
            domain_cards: tuple[DomainAgentCard, ...]: .
            worker_cards: tuple[WorkerAgentCard, ...]: .

        Returns:
            None: .
        """
        self._domain_cards = {card.name: card for card in domain_cards}
        self._worker_cards = {card.name: card for card in worker_cards}

    def require_domain_card(self, request: DomainTaskRequest) -> DomainAgentCard:
        """Require domain card.

        Args:
            request: DomainTaskRequest: .

        Returns:
            DomainAgentCard: .
        """
        try:
            return self._domain_cards[request.to_domain_agent]
        except KeyError as exc:
            raise KeyError(f"unknown domain agent: {request.to_domain_agent}") from exc

    def require_worker_card(self, request: WorkerTaskRequest) -> WorkerAgentCard:
        """Require worker card.

        Args:
            request: WorkerTaskRequest: .

        Returns:
            WorkerAgentCard: .
        """
        try:
            return self._worker_cards[request.worker_agent]
        except KeyError as exc:
            raise KeyError(f"unknown worker agent: {request.worker_agent}") from exc
