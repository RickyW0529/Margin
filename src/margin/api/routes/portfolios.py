"""Portfolio API routes for the Margin API.

This module implements the REST endpoints for managing portfolios, positions,
trades, CSV imports, risk reports, and investment theses. All routes live
under the ``/api/v1`` prefix and share the portfolio service dependency.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from margin.api.dependencies import get_portfolio_service
from margin.api.schemas import (
    CSVImportRequest,
    CSVImportResponse,
    PortfolioDashboardResponse,
    ThesisUpdate,
    TradeCreate,
)
from margin.portfolio.importer import ImportValidationError, TradeValidationError
from margin.portfolio.models import Position, PositionThesis, Trade
from margin.portfolio.risk import PortfolioRiskReport
from margin.portfolio.service import PortfolioService, PositionDetail

router = APIRouter(prefix="/api/v1", tags=["portfolio"])
"""APIRouter exposing portfolio-related endpoints under ``/api/v1``."""

Service = Annotated[PortfolioService, Depends(get_portfolio_service)]
"""FastAPI dependency type that injects a ``PortfolioService`` into handlers."""


def _not_found(exc: KeyError) -> HTTPException:
    """Convert a ``KeyError`` into an HTTP 404 exception.

    Args:
        exc: The original key error, typically raised when a portfolio or
            position identifier is not found.

    Returns:
        HTTPException: A 404 ``HTTPException`` carrying the original message.
    """
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get(
    "/portfolios/{portfolio_id}",
    response_model=PortfolioDashboardResponse,
)
def get_portfolio(portfolio_id: str, service: Service) -> PortfolioDashboardResponse:
    """Return portfolio identity and dashboard overview.

    Args:
        portfolio_id: Unique identifier of the portfolio to retrieve.
        service: Portfolio service used to load portfolio data.

    Returns:
        PortfolioDashboardResponse: Portfolio metadata together with aggregated
        dashboard metrics.

    Raises:
        HTTPException: 404 if the portfolio cannot be found.
    """
    try:
        return PortfolioDashboardResponse(
            portfolio=service.get_portfolio(portfolio_id),
            overview=service.get_overview(portfolio_id),
        )
    except KeyError as exc:
        raise _not_found(exc) from exc


@router.get(
    "/portfolios/{portfolio_id}/positions",
    response_model=list[Position],
)
def get_positions(portfolio_id: str, service: Service) -> list[Position]:
    """Return the current positions for a portfolio.

    Args:
        portfolio_id: Unique identifier of the portfolio.
        service: Portfolio service used to load positions.

    Returns:
        list[Position]: The list of positions held in the portfolio.

    Raises:
        HTTPException: 404 if the portfolio cannot be found.
    """
    try:
        return service.get_positions(portfolio_id)
    except KeyError as exc:
        raise _not_found(exc) from exc


@router.get(
    "/portfolios/{portfolio_id}/positions/{position_id}",
    response_model=PositionDetail,
)
def get_position_detail(
    portfolio_id: str,
    position_id: str,
    service: Service,
) -> PositionDetail:
    """Return a single position with its thesis and trade history.

    Args:
        portfolio_id: Unique identifier of the portfolio that owns the position.
        position_id: Unique identifier of the position.
        service: Portfolio service used to load position details.

    Returns:
        PositionDetail: Detailed position data including trades and thesis
        history.

    Raises:
        HTTPException: 404 if the portfolio or position cannot be found.
    """
    try:
        return service.get_position_detail(portfolio_id, position_id)
    except KeyError as exc:
        raise _not_found(exc) from exc


@router.post(
    "/portfolios/{portfolio_id}/trades",
    response_model=Trade,
    status_code=status.HTTP_201_CREATED,
)
def create_trade(
    portfolio_id: str,
    request: TradeCreate,
    service: Service,
) -> Trade:
    """Append a manually entered trade to a portfolio.

    Args:
        portfolio_id: Unique identifier of the portfolio that receives the
            trade.
        request: Validated trade creation request.
        service: Portfolio service used to persist the trade.

    Returns:
        Trade: The newly created trade.

    Raises:
        HTTPException: 404 if the portfolio cannot be found.
        HTTPException: 422 if the trade fails validation.
    """
    try:
        return service.add_trade(
            portfolio_id=portfolio_id,
            symbol=request.symbol,
            side=request.side.value,
            quantity=request.quantity,
            price=request.price,
            traded_at=request.traded_at,
            fee=request.fee,
            tax=request.tax,
            note=request.note,
        )
    except KeyError as exc:
        raise _not_found(exc) from exc
    except TradeValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


@router.post(
    "/portfolios/{portfolio_id}/imports",
    response_model=CSVImportResponse,
    status_code=status.HTTP_201_CREATED,
)
def import_trades(
    portfolio_id: str,
    request: CSVImportRequest,
    service: Service,
) -> CSVImportResponse:
    """Import trades from CSV content into a portfolio atomically.

    Args:
        portfolio_id: Unique identifier of the target portfolio.
        request: CSV import request containing raw CSV text and an optional
            field mapping.
        service: Portfolio service used to process the import.

    Returns:
        CSVImportResponse: The imported trades and the import record.

    Raises:
        HTTPException: 404 if the portfolio cannot be found.
        HTTPException: 422 if the CSV content fails validation, with details
            about the errors and the failing import record when available.
    """
    try:
        trades, record = service.import_csv(
            portfolio_id,
            request.content,
            request.field_mapping,
        )
        return CSVImportResponse(trades=trades, record=record)
    except KeyError as exc:
        raise _not_found(exc) from exc
    except ImportValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "message": str(exc),
                "errors": exc.errors,
                "record": exc.record.model_dump(mode="json") if exc.record else None,
            },
        ) from exc


@router.get(
    "/portfolios/{portfolio_id}/risk",
    response_model=PortfolioRiskReport,
)
def get_risk(portfolio_id: str, service: Service) -> PortfolioRiskReport:
    """Return the portfolio risk report.

    Args:
        portfolio_id: Unique identifier of the portfolio.
        service: Portfolio service used to generate the risk report.

    Returns:
        PortfolioRiskReport: Risk metrics and analysis for the portfolio.

    Raises:
        HTTPException: 404 if the portfolio cannot be found.
    """
    try:
        return service.get_risk(portfolio_id)
    except KeyError as exc:
        raise _not_found(exc) from exc


@router.get(
    "/positions/{position_id}/thesis",
    response_model=PositionThesis,
)
def get_thesis(
    position_id: str,
    service: Service,
    portfolio_id: Annotated[str, Query(min_length=1)],
) -> PositionThesis:
    """Return the latest thesis version for a position.

    Args:
        position_id: Unique identifier of the position.
        service: Portfolio service used to load the thesis history.
        portfolio_id: Unique identifier of the portfolio, supplied as a query
            parameter.

    Returns:
        PositionThesis: The most recent thesis entry for the position.

    Raises:
        HTTPException: 404 if the portfolio or position cannot be found, or if
            no thesis exists for the position.
    """
    try:
        service.get_position_detail(portfolio_id, position_id)
        history = service.get_thesis_history(portfolio_id, position_id)
    except KeyError as exc:
        raise _not_found(exc) from exc
    if not history:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No thesis found for position '{position_id}'",
        )
    return history[-1]


@router.put(
    "/positions/{position_id}/thesis",
    response_model=PositionThesis,
)
def update_thesis(
    position_id: str,
    request: ThesisUpdate,
    service: Service,
) -> PositionThesis:
    """Create a new immutable thesis version for a position.

    Args:
        position_id: Unique identifier of the position being updated.
        request: Validated thesis update request.
        service: Portfolio service used to persist the new thesis version.

    Returns:
        PositionThesis: The newly created thesis entry.

    Raises:
        HTTPException: 404 if the portfolio or position cannot be found.
    """
    try:
        service.get_position_detail(request.portfolio_id, position_id)
        return service.update_thesis(
            portfolio_id=request.portfolio_id,
            position_id=position_id,
            thesis=request.thesis,
            entry_conditions=request.entry_conditions,
            hold_conditions=request.hold_conditions,
            invalidation_conditions=request.invalidation_conditions,
            target_horizon=request.target_horizon,
            next_review_at=request.next_review_at,
            status=request.status,
        )
    except KeyError as exc:
        raise _not_found(exc) from exc
