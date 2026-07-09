"""Strategy configuration API routes for the Margin API.

Routes live under ``/api/v1/strategies`` so the Next.js BFF can proxy them with
the same Authorization and Idempotency-Key handling as other mutating APIs.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, ValidationError

from margin.api.dependencies import (
    get_idempotency_store,
    get_strategy_service,
    require_idempotency_key,
    require_local_admin,
)
from margin.api.idempotency import begin_idempotent, complete_idempotent
from margin.strategy.service import StrategyService

router = APIRouter(prefix="/api/v1/strategies", tags=["strategy"])

_STRATEGY_SCOPE = "strategy.lifecycle"
ServiceDep = Annotated[StrategyService, Depends(get_strategy_service)]
IdempotencyKeyDep = Annotated[str, Depends(require_idempotency_key)]
ActorDep = Annotated[str, Depends(require_local_admin)]
IdempotencyStoreDep = Annotated[Any, Depends(get_idempotency_store)]


class CreateStrategyRequest(BaseModel):
    """Request body for creating a strategy from a built-in template."""

    owner_id: str = Field(min_length=1)
    template: str = Field(default="custom")
    name: str = ""
    description: str = ""


class CreateCustomStrategyRequest(BaseModel):
    """Request body for creating a strategy from a custom configuration."""

    owner_id: str = Field(min_length=1)
    config: dict[str, Any]
    name: str = Field(min_length=1)
    description: str = ""


class UpdateStrategyRequest(BaseModel):
    """Request body for creating a new version of an existing strategy."""

    config_delta: dict[str, Any] = Field(default_factory=dict)
    name: str | None = None
    description: str | None = None


class PromptResponse(BaseModel):
    """Response payload containing a merged strategy prompt."""

    prompt: str


@router.get("/templates")
def list_templates(service: ServiceDep) -> list[dict[str, str]]:
    """Return metadata for all built-in strategy templates."""
    return [
        {
            "template_id": meta.template_id,
            "name": meta.name,
            "description": meta.description,
            "category": meta.category,
        }
        for meta in service.list_templates()
    ]


@router.post("")
def create_strategy(
    request: CreateStrategyRequest,
    service: ServiceDep,
    idempotency_key: IdempotencyKeyDep,
    _actor_id: ActorDep,
    idempotency_store: IdempotencyStoreDep,
) -> dict[str, Any]:
    """Create a new strategy from a built-in template."""
    begun = begin_idempotent(
        idempotency_store,
        scope=_STRATEGY_SCOPE,
        idempotency_key=idempotency_key,
        request_payload={"action": "create", **request.model_dump(mode="json")},
    )
    if begun.replay_payload is not None:
        return begun.replay_payload
    try:
        profile = service.create_from_template(
            owner_id=request.owner_id,
            template_id=request.template,
            name=request.name,
            description=request.description,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return complete_idempotent(
        idempotency_store,
        scope=_STRATEGY_SCOPE,
        scoped_key=begun.scoped_key,
        request_hash=begun.request_hash,
        response_payload=profile.model_dump(mode="json"),
    )


@router.post("/custom")
def create_custom_strategy(
    request: CreateCustomStrategyRequest,
    service: ServiceDep,
    idempotency_key: IdempotencyKeyDep,
    _actor_id: ActorDep,
    idempotency_store: IdempotencyStoreDep,
) -> dict[str, Any]:
    """Create a new strategy from a fully custom configuration."""
    from margin.strategy.models import StrategyConfig

    begun = begin_idempotent(
        idempotency_store,
        scope=_STRATEGY_SCOPE,
        idempotency_key=idempotency_key,
        request_payload={"action": "create_custom", **request.model_dump(mode="json")},
    )
    if begun.replay_payload is not None:
        return begun.replay_payload
    try:
        config = StrategyConfig.model_validate(request.config)
        profile = service.create_custom(
            owner_id=request.owner_id,
            config=config,
            name=request.name,
            description=request.description,
        )
    except (ValueError, ValidationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return complete_idempotent(
        idempotency_store,
        scope=_STRATEGY_SCOPE,
        scoped_key=begun.scoped_key,
        request_hash=begun.request_hash,
        response_payload=profile.model_dump(mode="json"),
    )


@router.get("")
def list_strategies(owner_id: str, service: ServiceDep) -> list[dict[str, Any]]:
    """List all strategy profiles owned by the given owner."""
    return [profile.model_dump(mode="json") for profile in service.list_profiles(owner_id)]


@router.get("/{strategy_id}")
def get_strategy(strategy_id: str, service: ServiceDep) -> dict[str, Any]:
    """Return a single strategy profile."""
    try:
        return service.get_profile(strategy_id).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.put("/{strategy_id}")
def update_strategy(
    strategy_id: str,
    request: UpdateStrategyRequest,
    service: ServiceDep,
    idempotency_key: IdempotencyKeyDep,
    _actor_id: ActorDep,
    idempotency_store: IdempotencyStoreDep,
) -> dict[str, Any]:
    """Create a new version of an existing strategy."""
    begun = begin_idempotent(
        idempotency_store,
        scope=_STRATEGY_SCOPE,
        idempotency_key=idempotency_key,
        request_payload={
            "action": "update",
            "strategy_id": strategy_id,
            **request.model_dump(mode="json"),
        },
    )
    if begun.replay_payload is not None:
        return begun.replay_payload
    try:
        profile = service.update_strategy(
            strategy_id=strategy_id,
            config_delta=request.config_delta,
            name=request.name,
            description=request.description,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return complete_idempotent(
        idempotency_store,
        scope=_STRATEGY_SCOPE,
        scoped_key=begun.scoped_key,
        request_hash=begun.request_hash,
        response_payload=profile.model_dump(mode="json"),
    )


@router.post("/{strategy_id}/versions/{version_id}/validate")
def validate_version(
    strategy_id: str,
    version_id: str,
    service: ServiceDep,
    idempotency_key: IdempotencyKeyDep,
    _actor_id: ActorDep,
    idempotency_store: IdempotencyStoreDep,
) -> dict[str, Any]:
    """Validate a strategy version and advance it to the backtesting stage."""
    return _lifecycle_mutation(
        idempotency_store=idempotency_store,
        idempotency_key=idempotency_key,
        action="validate",
        strategy_id=strategy_id,
        version_id=version_id,
        mutate=lambda: service.validate_version(strategy_id, version_id),
    )


@router.post("/{strategy_id}/versions/{version_id}/backtest")
def backtest_version(
    strategy_id: str,
    version_id: str,
    service: ServiceDep,
    idempotency_key: IdempotencyKeyDep,
    _actor_id: ActorDep,
    idempotency_store: IdempotencyStoreDep,
) -> dict[str, Any]:
    """Advance a strategy version from backtesting to paper trading."""
    return _lifecycle_mutation(
        idempotency_store=idempotency_store,
        idempotency_key=idempotency_key,
        action="backtest",
        strategy_id=strategy_id,
        version_id=version_id,
        mutate=lambda: service.backtest_version(strategy_id, version_id),
    )


@router.post("/{strategy_id}/versions/{version_id}/paper-trade")
def paper_trade_version(
    strategy_id: str,
    version_id: str,
    service: ServiceDep,
    idempotency_key: IdempotencyKeyDep,
    _actor_id: ActorDep,
    idempotency_store: IdempotencyStoreDep,
) -> dict[str, Any]:
    """Advance a strategy version from paper trading to active-ready."""
    return _lifecycle_mutation(
        idempotency_store=idempotency_store,
        idempotency_key=idempotency_key,
        action="paper_trade",
        strategy_id=strategy_id,
        version_id=version_id,
        mutate=lambda: service.paper_trade_version(strategy_id, version_id),
    )


@router.post("/{strategy_id}/versions/{version_id}/activate")
def activate_version(
    strategy_id: str,
    version_id: str,
    service: ServiceDep,
    idempotency_key: IdempotencyKeyDep,
    _actor_id: ActorDep,
    idempotency_store: IdempotencyStoreDep,
) -> dict[str, Any]:
    """Activate a strategy version for live research runs."""
    return _lifecycle_mutation(
        idempotency_store=idempotency_store,
        idempotency_key=idempotency_key,
        action="activate",
        strategy_id=strategy_id,
        version_id=version_id,
        mutate=lambda: service.activate_version(strategy_id, version_id),
    )


@router.post("/{strategy_id}/archive")
def archive_strategy(
    strategy_id: str,
    service: ServiceDep,
    idempotency_key: IdempotencyKeyDep,
    _actor_id: ActorDep,
    idempotency_store: IdempotencyStoreDep,
) -> dict[str, Any]:
    """Archive the active version of a strategy."""
    begun = begin_idempotent(
        idempotency_store,
        scope=_STRATEGY_SCOPE,
        idempotency_key=idempotency_key,
        request_payload={"action": "archive", "strategy_id": strategy_id},
    )
    if begun.replay_payload is not None:
        return begun.replay_payload
    try:
        profile = service.archive_strategy(strategy_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return complete_idempotent(
        idempotency_store,
        scope=_STRATEGY_SCOPE,
        scoped_key=begun.scoped_key,
        request_hash=begun.request_hash,
        response_payload=profile.model_dump(mode="json"),
    )


@router.get("/{strategy_id}/versions/{version_id}/prompt")
def get_prompt(
    strategy_id: str,
    version_id: str,
    service: ServiceDep,
    task: str = "",
) -> PromptResponse:
    """Return the merged prompt for a strategy version and task."""
    try:
        prompt = service.get_prompt(strategy_id, version_id, task=task)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return PromptResponse(prompt=prompt)


def _lifecycle_mutation(
    *,
    idempotency_store: Any,
    idempotency_key: str,
    action: str,
    strategy_id: str,
    version_id: str,
    mutate: Any,
) -> dict[str, Any]:
    """Run one version lifecycle mutation behind HTTP idempotency."""
    begun = begin_idempotent(
        idempotency_store,
        scope=_STRATEGY_SCOPE,
        idempotency_key=idempotency_key,
        request_payload={
            "action": action,
            "strategy_id": strategy_id,
            "version_id": version_id,
        },
    )
    if begun.replay_payload is not None:
        return begun.replay_payload
    try:
        profile = mutate()
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return complete_idempotent(
        idempotency_store,
        scope=_STRATEGY_SCOPE,
        scoped_key=begun.scoped_key,
        request_hash=begun.request_hash,
        response_payload=profile.model_dump(mode="json"),
    )
