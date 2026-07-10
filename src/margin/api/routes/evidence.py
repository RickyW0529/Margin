"""Canonical evidence source detail API."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from margin.api.dependencies import get_app_container
from margin.bootstrap.container import AppContainer
from margin.evidence.detail import (
    EvidenceDetail,
    EvidenceDetailService,
    SQLAlchemyQuantResultDetailRepository,
    SQLAlchemyWarehouseFactDetailRepository,
)
from margin.evidence.repository import EvidenceRepository
from margin.news.repository import NewsRepository

router = APIRouter(prefix="/api/v1/evidence", tags=["evidence"])


def get_evidence_detail_service(
    container: Annotated[AppContainer, Depends(get_app_container)],
) -> EvidenceDetailService:
    """Build the canonical evidence detail read service."""
    session_factory = container.session_factory
    return EvidenceDetailService(
        evidence_reader=EvidenceRepository(session_factory),
        document_reader=NewsRepository(session_factory),
        warehouse_fact_reader=SQLAlchemyWarehouseFactDetailRepository(session_factory),
        quant_result_reader=SQLAlchemyQuantResultDetailRepository(session_factory),
    )


@router.get("/{evidence_id}", response_model=EvidenceDetail)
def get_evidence_detail(
    evidence_id: str,
    service: Annotated[EvidenceDetailService, Depends(get_evidence_detail_service)],
) -> EvidenceDetail:
    """Return complete canonical Markdown and verified highlight ranges."""
    detail = service.get_detail(evidence_id)
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="evidence not found",
        )
    return detail


__all__ = ["get_evidence_detail_service", "router"]
