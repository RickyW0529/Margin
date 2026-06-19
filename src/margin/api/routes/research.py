"""Research API routes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from margin.api.dependencies import get_research_service
from margin.research.service import ResearchService

router = APIRouter(prefix="/research", tags=["research"])


class ResearchRunRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    decision_at: datetime | None = None
    portfolio_id: str | None = None

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("symbol must not be blank")
        return normalized


class ResearchRunResponse(BaseModel):
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
    return service.list_tools()
