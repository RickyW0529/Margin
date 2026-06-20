"""Research API routes for the Margin API.

This module exposes endpoints for running research workflows against a symbol
and for listing the tools available to the research service. Research runs are
synchronous in the current MVP and return structured signals together with
optional snapshot metadata.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from margin.api.dependencies import get_research_service
from margin.research.service import ResearchService

router = APIRouter(prefix="/research", tags=["research"])
"""APIRouter exposing research-related endpoints under ``/research``."""


class ResearchRunRequest(BaseModel):
    """Request body for triggering a research run.

    Attributes:
        symbol: Ticker or instrument identifier to research. Normalised to
            uppercase and stripped of surrounding whitespace.
        decision_at: Optional timestamp that anchors the research decision.
            Defaults to the current time when omitted.
        portfolio_id: Optional portfolio identifier used to scope the research.
    """

    symbol: str = Field(min_length=1, max_length=32)
    decision_at: datetime | None = None
    portfolio_id: str | None = None

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        """Normalise a symbol by stripping whitespace and upper-casing it.

        Args:
            value: Raw symbol value from the request.

        Returns:
            str: Normalised symbol string.

        Raises:
            ValueError: If the normalised symbol is empty.
        """
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("symbol must not be blank")
        return normalized


class ResearchRunResponse(BaseModel):
    """Response payload returned after a research run completes.

    Attributes:
        run_id: Unique identifier assigned to the research run.
        state: Terminal state of the run, e.g. ``completed`` or ``aborted``.
        signals: Structured signals produced by the research workflow.
        snapshot_id: Identifier of the persisted snapshot, when one was saved.
        error: Human-readable error message when the run did not succeed.
    """

    run_id: str
    state: str
    signals: list[dict[str, Any]]
    snapshot_id: str | None = None
    error: str | None = None

    model_config = {"frozen": True}


@router.post("/run")
def run_research(
    request: ResearchRunRequest,
    service: ResearchService = Depends(get_research_service),
) -> ResearchRunResponse:
    """Execute a research run for the requested symbol.

    Args:
        request: Validated research run request containing the symbol and
            optional context.
        service: Research service used to execute the workflow.

    Returns:
        ResearchRunResponse: The run identifier, terminal state, signals, and
        optional snapshot identifier.

    Raises:
        HTTPException: 422 if the research workflow aborts.
    """
    result = service.run(
        symbol=request.symbol,
        decision_at=request.decision_at,
        portfolio_id=request.portfolio_id,
    )
    if result.state in ("aborted",):
        raise HTTPException(status_code=422, detail=result.error or "workflow aborted")
    return ResearchRunResponse(
        run_id=result.run_id,
        state=result.state,
        signals=[s.model_dump() for s in result.signals],
        snapshot_id=(
            (result.snapshot or {}).get("snapshot_id")
            if result.snapshot_persisted
            else None
        ),
        error=result.error,
    )


@router.get("/tools")
def list_tools(
    service: ResearchService = Depends(get_research_service),
) -> list[dict[str, str]]:
    """List the tools registered with the research service.

    Args:
        service: Research service that owns the tool registry.

    Returns:
        list[dict[str, str]]: Metadata for each available tool.
    """
    return service.list_tools()
