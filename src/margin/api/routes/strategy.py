"""Strategy configuration API routes for the Margin API.

This module implements the REST endpoints used to manage investment strategy
profiles and their versioned lifecycles. Strategies can be created from
built-in templates or from fully custom configurations, then progressed through
validation, backtesting, paper trading, and activation stages.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, ValidationError

from margin.api.dependencies import get_strategy_service, require_idempotency_key
from margin.strategy.service import StrategyService

router = APIRouter(prefix="/strategies", tags=["strategy"])
"""APIRouter exposing strategy-related endpoints under ``/strategies``."""


class CreateStrategyRequest(BaseModel):
    """Request body for creating a strategy from a built-in template.

    Attributes:
        owner_id: Identifier of the user or entity that owns the strategy.
        template: Template identifier to instantiate. Defaults to ``custom``.
        name: Human-readable name for the new strategy.
        description: Optional longer description of the strategy.
    """

    owner_id: str = Field(min_length=1)
    template: str = Field(default="custom")
    name: str = ""
    description: str = ""


class CreateCustomStrategyRequest(BaseModel):
    """Request body for creating a strategy from a custom configuration.

    Attributes:
        owner_id: Identifier of the user or entity that owns the strategy.
        config: Complete strategy configuration object validated against
            ``StrategyConfig``.
        name: Human-readable name for the new strategy.
        description: Optional longer description of the strategy.
    """

    owner_id: str = Field(min_length=1)
    config: dict[str, Any]
    name: str = Field(min_length=1)
    description: str = ""


class UpdateStrategyRequest(BaseModel):
    """Request body for creating a new version of an existing strategy.

    Attributes:
        config_delta: Partial configuration updates to apply to the latest
            version. Defaults to an empty dictionary.
        name: Optional new name for the strategy.
        description: Optional new description for the strategy.
    """

    config_delta: dict[str, Any] = Field(default_factory=dict)
    name: str | None = None
    description: str | None = None


class PromptResponse(BaseModel):
    """Response payload containing a merged strategy prompt.

    Attributes:
        prompt: The final merged prompt text.
    """

    prompt: str


@router.get("/templates")
def list_templates(
    service: StrategyService = Depends(get_strategy_service),
) -> list[dict[str, str]]:
    """Return metadata for all built-in strategy templates.

    Args:
        service: Strategy service that owns the template registry.

    Returns:
        list[dict[str, str]]: Template metadata including identifier, name,
        description, and category.
    """
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
    service: StrategyService = Depends(get_strategy_service),
    _idempotency_key: str = Depends(require_idempotency_key),
) -> dict[str, Any]:
    """Create a new strategy from a built-in template.

    Args:
        request: Validated strategy creation request.
        service: Strategy service used to instantiate the profile.

    Returns:
        dict[str, Any]: The newly created strategy profile serialised as a
        dictionary.

    Raises:
        HTTPException: 400 if the requested template is unknown or the request
            is otherwise invalid.
    """
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
    return profile.model_dump()


@router.post("/custom")
def create_custom_strategy(
    request: CreateCustomStrategyRequest,
    service: StrategyService = Depends(get_strategy_service),
    _idempotency_key: str = Depends(require_idempotency_key),
) -> dict[str, Any]:
    """Create a new strategy from a fully custom configuration.

    Args:
        request: Validated custom strategy creation request.
        service: Strategy service used to instantiate the profile.

    Returns:
        dict[str, Any]: The newly created custom strategy profile serialised as
        a dictionary.

    Raises:
        HTTPException: 400 if the configuration fails validation.
    """
    from margin.strategy.models import StrategyConfig

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
    return profile.model_dump()


@router.get("")
def list_strategies(
    owner_id: str,
    service: StrategyService = Depends(get_strategy_service),
) -> list[dict[str, Any]]:
    """List all strategy profiles owned by the given owner.

    Args:
        owner_id: Identifier of the owner whose strategies should be listed.
        service: Strategy service used to query profiles.

    Returns:
        list[dict[str, Any]]: Serialised strategy profiles for the owner.
    """
    return [profile.model_dump() for profile in service.list_profiles(owner_id)]


@router.get("/{strategy_id}")
def get_strategy(
    strategy_id: str,
    service: StrategyService = Depends(get_strategy_service),
) -> dict[str, Any]:
    """Return a single strategy profile.

    Args:
        strategy_id: Unique identifier of the strategy.
        service: Strategy service used to load the profile.

    Returns:
        dict[str, Any]: The requested strategy profile serialised as a
        dictionary.

    Raises:
        HTTPException: 404 if the strategy cannot be found.
    """
    try:
        return service.get_profile(strategy_id).model_dump()
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.put("/{strategy_id}")
def update_strategy(
    strategy_id: str,
    request: UpdateStrategyRequest,
    service: StrategyService = Depends(get_strategy_service),
    _idempotency_key: str = Depends(require_idempotency_key),
) -> dict[str, Any]:
    """Create a new version of an existing strategy.

    Args:
        strategy_id: Unique identifier of the strategy to update.
        request: Validated update request containing optional configuration
            deltas and metadata changes.
        service: Strategy service used to create the new version.

    Returns:
        dict[str, Any]: The newly created strategy version serialised as a
        dictionary.

    Raises:
        HTTPException: 404 if the strategy cannot be found.
        HTTPException: 400 if the update request is invalid.
    """
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
    return profile.model_dump()


@router.post("/{strategy_id}/versions/{version_id}/validate")
def validate_version(
    strategy_id: str,
    version_id: str,
    service: StrategyService = Depends(get_strategy_service),
    _idempotency_key: str = Depends(require_idempotency_key),
) -> dict[str, Any]:
    """Validate a strategy version and advance it to the backtesting stage.

    Args:
        strategy_id: Unique identifier of the strategy.
        version_id: Unique identifier of the version to validate.
        service: Strategy service used to advance the version.

    Returns:
        dict[str, Any]: The updated strategy version serialised as a dictionary.

    Raises:
        HTTPException: 404 if the strategy or version cannot be found.
        HTTPException: 400 if the version cannot be validated.
    """
    try:
        return service.validate_version(strategy_id, version_id).model_dump()
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


@router.post("/{strategy_id}/versions/{version_id}/backtest")
def backtest_version(
    strategy_id: str,
    version_id: str,
    service: StrategyService = Depends(get_strategy_service),
    _idempotency_key: str = Depends(require_idempotency_key),
) -> dict[str, Any]:
    """Advance a strategy version from backtesting to paper trading.

    Args:
        strategy_id: Unique identifier of the strategy.
        version_id: Unique identifier of the version to backtest.
        service: Strategy service used to advance the version.

    Returns:
        dict[str, Any]: The updated strategy version serialised as a dictionary.

    Raises:
        HTTPException: 404 if the strategy or version cannot be found.
        HTTPException: 400 if the version cannot be backtested.
    """
    try:
        return service.backtest_version(strategy_id, version_id).model_dump()
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


@router.post("/{strategy_id}/versions/{version_id}/paper-trade")
def paper_trade_version(
    strategy_id: str,
    version_id: str,
    service: StrategyService = Depends(get_strategy_service),
    _idempotency_key: str = Depends(require_idempotency_key),
) -> dict[str, Any]:
    """Advance a strategy version from paper trading to active-ready.

    Args:
        strategy_id: Unique identifier of the strategy.
        version_id: Unique identifier of the version to paper trade.
        service: Strategy service used to advance the version.

    Returns:
        dict[str, Any]: The updated strategy version serialised as a dictionary.

    Raises:
        HTTPException: 404 if the strategy or version cannot be found.
        HTTPException: 400 if the version cannot be paper traded.
    """
    try:
        return service.paper_trade_version(strategy_id, version_id).model_dump()
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


@router.post("/{strategy_id}/versions/{version_id}/activate")
def activate_version(
    strategy_id: str,
    version_id: str,
    service: StrategyService = Depends(get_strategy_service),
    _idempotency_key: str = Depends(require_idempotency_key),
) -> dict[str, Any]:
    """Activate a strategy version for live research runs.

    Args:
        strategy_id: Unique identifier of the strategy.
        version_id: Unique identifier of the version to activate.
        service: Strategy service used to activate the version.

    Returns:
        dict[str, Any]: The updated strategy version serialised as a dictionary.

    Raises:
        HTTPException: 404 if the strategy or version cannot be found.
        HTTPException: 400 if the version cannot be activated.
    """
    try:
        return service.activate_version(strategy_id, version_id).model_dump()
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


@router.post("/{strategy_id}/archive")
def archive_strategy(
    strategy_id: str,
    service: StrategyService = Depends(get_strategy_service),
    _idempotency_key: str = Depends(require_idempotency_key),
) -> dict[str, Any]:
    """Archive the active version of a strategy.

    Args:
        strategy_id: Unique identifier of the strategy to archive.
        service: Strategy service used to archive the active version.

    Returns:
        dict[str, Any]: The updated strategy profile serialised as a dictionary.

    Raises:
        HTTPException: 404 if the strategy cannot be found.
        HTTPException: 400 if the strategy cannot be archived.
    """
    try:
        return service.archive_strategy(strategy_id).model_dump()
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


@router.get("/{strategy_id}/versions/{version_id}/prompt")
def get_prompt(
    strategy_id: str,
    version_id: str,
    task: str = "",
    service: StrategyService = Depends(get_strategy_service),
) -> PromptResponse:
    """Return the merged prompt for a strategy version and task.

    Args:
        strategy_id: Unique identifier of the strategy.
        version_id: Unique identifier of the version whose prompt is requested.
        task: Optional task name used to specialise the merged prompt.
        service: Strategy service used to build the prompt.

    Returns:
        PromptResponse: The merged prompt wrapped in a response model.

    Raises:
        HTTPException: 404 if the strategy or version cannot be found.
    """
    try:
        prompt = service.get_prompt(strategy_id, version_id, task=task)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return PromptResponse(prompt=prompt)
