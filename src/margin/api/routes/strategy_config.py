"""v0.2 versioned strategy configuration API."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import TypeVar

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from margin.api.dependencies import (
    get_optional_secret_store,
    get_provider_config_health_service,
    get_secret_store,
    get_strategy_service,
    require_idempotency_key,
    require_local_admin,
)
from margin.core.secret_store import SecretMetadata, SecretStore
from margin.strategy.models import (
    IndicatorViewVersion,
    ProviderConfigVersion,
    QuantFeatureSetVersion,
    QuantStrategyVersion,
    ResearchScopeVersion,
    UniverseDefinitionVersion,
    UserStylePromptVersion,
)
from margin.strategy.provider_config import ProviderConfigHealthService, ProviderHealth
from margin.strategy.service import StrategyService

router = APIRouter(prefix="/api/v1", tags=["strategy-config-v0.2"])
T = TypeVar("T")


class WriteProviderSecretRequest(BaseModel):
    """Write-only provider secret request."""

    secret_name: str
    secret_value: str


class SecretMetadataResponse(BaseModel):
    """Safe provider secret metadata response."""

    configured: bool
    last_four: str
    version_id: str
    status: str
    updated_at: datetime
    provider_name: str
    secret_name: str

    @classmethod
    def from_metadata(cls, metadata: SecretMetadata) -> SecretMetadataResponse:
        """Build a response without plaintext, ciphertext, nonce, or key material."""
        return cls(
            configured=metadata.configured,
            last_four=metadata.last_four,
            version_id=metadata.version_id,
            status=metadata.status,
            updated_at=metadata.updated_at,
            provider_name=metadata.ref.provider_name,
            secret_name=metadata.ref.secret_name,
        )


class ProviderConfigResponse(BaseModel):
    """Safe provider config summary for the settings UI."""

    version_id: str
    provider_name: str
    provider_type: str
    enabled: bool
    lifecycle: str
    base_url: str | None
    model_name: str | None
    secret_metadata: SecretMetadataResponse | None

    @classmethod
    def from_version(
        cls,
        version: ProviderConfigVersion,
        secret_store: SecretStore | None,
    ) -> ProviderConfigResponse:
        """Build a safe response with optional write-only secret metadata."""
        secret_metadata = None
        if version.secret_version_id and secret_store is not None:
            secret_metadata = SecretMetadataResponse.from_metadata(
                secret_store.metadata(version.secret_version_id)
            )
        return cls(
            version_id=version.version_id,
            provider_name=version.provider_name,
            provider_type=version.provider_type,
            enabled=version.enabled,
            lifecycle=version.lifecycle.value,
            base_url=version.base_url,
            model_name=version.model_name,
            secret_metadata=secret_metadata,
        )


@router.get("/provider-configs")
def list_provider_configs(
    owner_id: str = "local-admin",
    service: StrategyService = Depends(get_strategy_service),
    secret_store: SecretStore | None = Depends(get_optional_secret_store),
) -> list[ProviderConfigResponse]:
    """List provider config versions without returning secret contents."""
    return [
        ProviderConfigResponse.from_version(version, secret_store)
        for version in service.list_provider_configs(owner_id)
    ]


@router.post("/provider-configs")
def create_provider_config(
    version: ProviderConfigVersion,
    actor_id: str = Depends(require_local_admin),
    idempotency_key: str = Depends(require_idempotency_key),
    service: StrategyService = Depends(get_strategy_service),
) -> ProviderConfigVersion:
    """Create an append-only provider configuration version."""
    return _call_service(
        lambda: service.create_provider_config(
            version,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
        )
    )


@router.put("/provider-configs/{version_id}/secret")
def write_provider_secret(
    version_id: str,
    request: WriteProviderSecretRequest,
    actor_id: str = Depends(require_local_admin),
    idempotency_key: str = Depends(require_idempotency_key),
    service: StrategyService = Depends(get_strategy_service),
    secret_store: SecretStore = Depends(get_secret_store),
) -> SecretMetadataResponse:
    """Encrypt and bind a provider secret, returning metadata only."""
    metadata = _call_service(
        lambda: service.write_provider_secret(
            provider_config_version_id=version_id,
            secret_name=request.secret_name,
            secret_value=request.secret_value,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            secret_store=secret_store,
        )
    )
    return SecretMetadataResponse.from_metadata(metadata)


@router.post("/provider-configs/{version_id}/test")
def test_provider_config(
    version_id: str,
    _actor_id: str = Depends(require_local_admin),
    _idempotency_key: str = Depends(require_idempotency_key),
    health_service: ProviderConfigHealthService = Depends(
        get_provider_config_health_service
    ),
) -> ProviderHealth:
    """Run a read-only health check for a frozen provider config version."""
    return _call_service(
        lambda: health_service.test_connection(
            provider_config_version_id=version_id
        )
    )


@router.post("/provider-configs/{version_id}/activate")
def activate_provider_config(
    version_id: str,
    actor_id: str = Depends(require_local_admin),
    idempotency_key: str = Depends(require_idempotency_key),
    service: StrategyService = Depends(get_strategy_service),
    health_service: ProviderConfigHealthService = Depends(
        get_provider_config_health_service
    ),
) -> ProviderConfigVersion:
    """Activate a provider config version."""
    return _call_service(
        lambda: service.activate_provider_config(
            version_id,
            health_service=health_service,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
        )
    )


@router.get("/universe-configs")
def list_universe_configs(
    owner_id: str = "local-admin",
    service: StrategyService = Depends(get_strategy_service),
) -> list[UniverseDefinitionVersion]:
    """List universe definition versions."""
    return service.list_universe_definitions(owner_id)


@router.post("/universe-configs")
def create_universe_config(
    version: UniverseDefinitionVersion,
    actor_id: str = Depends(require_local_admin),
    idempotency_key: str = Depends(require_idempotency_key),
    service: StrategyService = Depends(get_strategy_service),
) -> UniverseDefinitionVersion:
    """Create an append-only universe definition version."""
    return _call_service(
        lambda: service.create_universe_definition(
            version,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
        )
    )


@router.post("/universe-configs/{version_id}/activate")
def activate_universe_config(
    version_id: str,
    actor_id: str = Depends(require_local_admin),
    idempotency_key: str = Depends(require_idempotency_key),
    service: StrategyService = Depends(get_strategy_service),
) -> UniverseDefinitionVersion:
    """Activate a universe definition version."""
    return _call_service(
        lambda: service.activate_universe_definition(
            version_id,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
        )
    )


@router.get("/indicator-views")
def list_indicator_views(
    owner_id: str = "local-admin",
    service: StrategyService = Depends(get_strategy_service),
) -> list[IndicatorViewVersion]:
    """List indicator view versions."""
    return service.list_indicator_views(owner_id)


@router.post("/indicator-views")
def create_indicator_view(
    version: IndicatorViewVersion,
    actor_id: str = Depends(require_local_admin),
    idempotency_key: str = Depends(require_idempotency_key),
    service: StrategyService = Depends(get_strategy_service),
) -> IndicatorViewVersion:
    """Create an append-only indicator view version."""
    return _call_service(
        lambda: service.create_indicator_view(
            version,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
        )
    )


@router.post("/indicator-views/{version_id}/activate")
def activate_indicator_view(
    version_id: str,
    actor_id: str = Depends(require_local_admin),
    idempotency_key: str = Depends(require_idempotency_key),
    service: StrategyService = Depends(get_strategy_service),
) -> IndicatorViewVersion:
    """Activate an indicator view version."""
    return _call_service(
        lambda: service.activate_indicator_view(
            version_id,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
        )
    )


@router.get("/quant-feature-sets")
def list_quant_feature_sets(
    owner_id: str = "local-admin",
    service: StrategyService = Depends(get_strategy_service),
) -> list[QuantFeatureSetVersion]:
    """List quant feature set versions."""
    return service.list_quant_feature_sets(owner_id)


@router.post("/quant-feature-sets")
def create_quant_feature_set(
    version: QuantFeatureSetVersion,
    actor_id: str = Depends(require_local_admin),
    idempotency_key: str = Depends(require_idempotency_key),
    service: StrategyService = Depends(get_strategy_service),
) -> QuantFeatureSetVersion:
    """Create an append-only quant feature set version."""
    return _call_service(
        lambda: service.create_quant_feature_set(
            version,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
        )
    )


@router.post("/quant-feature-sets/{version_id}/activate")
def activate_quant_feature_set(
    version_id: str,
    actor_id: str = Depends(require_local_admin),
    idempotency_key: str = Depends(require_idempotency_key),
    service: StrategyService = Depends(get_strategy_service),
) -> QuantFeatureSetVersion:
    """Activate a quant feature set version."""
    return _call_service(
        lambda: service.activate_quant_feature_set(
            version_id,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
        )
    )


@router.get("/quant-strategies")
def list_quant_strategies(
    owner_id: str = "local-admin",
    service: StrategyService = Depends(get_strategy_service),
) -> list[QuantStrategyVersion]:
    """List quant strategy versions."""
    return service.list_quant_strategies(owner_id)


@router.post("/quant-strategies")
def create_quant_strategy(
    version: QuantStrategyVersion,
    actor_id: str = Depends(require_local_admin),
    idempotency_key: str = Depends(require_idempotency_key),
    service: StrategyService = Depends(get_strategy_service),
) -> QuantStrategyVersion:
    """Create an append-only quant strategy version."""
    return _call_service(
        lambda: service.create_quant_strategy(
            version,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
        )
    )


@router.post("/quant-strategies/{version_id}/activate")
def activate_quant_strategy(
    version_id: str,
    actor_id: str = Depends(require_local_admin),
    idempotency_key: str = Depends(require_idempotency_key),
    service: StrategyService = Depends(get_strategy_service),
) -> QuantStrategyVersion:
    """Activate a calibrated quant strategy version."""
    return _call_service(
        lambda: service.activate_quant_strategy(
            version_id,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
        )
    )


@router.get("/style-prompts")
def list_style_prompts(
    owner_id: str = "local-admin",
    service: StrategyService = Depends(get_strategy_service),
) -> list[UserStylePromptVersion]:
    """List user style prompt versions."""
    return service.list_user_style_prompts(owner_id)


@router.post("/style-prompts")
def create_style_prompt(
    version: UserStylePromptVersion,
    actor_id: str = Depends(require_local_admin),
    idempotency_key: str = Depends(require_idempotency_key),
    service: StrategyService = Depends(get_strategy_service),
) -> UserStylePromptVersion:
    """Create an append-only user style prompt version."""
    return _call_service(
        lambda: service.create_user_style_prompt(
            version,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
        )
    )


@router.post("/style-prompts/{version_id}/activate")
def activate_style_prompt(
    version_id: str,
    actor_id: str = Depends(require_local_admin),
    idempotency_key: str = Depends(require_idempotency_key),
    service: StrategyService = Depends(get_strategy_service),
) -> UserStylePromptVersion:
    """Activate a style prompt after protected-boundary validation."""
    return _call_service(
        lambda: service.activate_user_style_prompt(
            version_id,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
        )
    )


@router.get("/research-scopes")
def list_research_scopes(
    owner_id: str = "local-admin",
    service: StrategyService = Depends(get_strategy_service),
) -> list[ResearchScopeVersion]:
    """List frozen research scope versions."""
    return service.list_research_scopes(owner_id)


@router.post("/research-scopes")
def create_research_scope(
    version: ResearchScopeVersion,
    actor_id: str = Depends(require_local_admin),
    idempotency_key: str = Depends(require_idempotency_key),
    service: StrategyService = Depends(get_strategy_service),
) -> ResearchScopeVersion:
    """Create an append-only frozen research scope version."""
    return _call_service(
        lambda: service.create_research_scope(
            version,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
        )
    )


@router.post("/research-scopes/{version_id}/activate")
def activate_research_scope(
    version_id: str,
    actor_id: str = Depends(require_local_admin),
    idempotency_key: str = Depends(require_idempotency_key),
    service: StrategyService = Depends(get_strategy_service),
) -> ResearchScopeVersion:
    """Activate a validated frozen research scope version."""
    return _call_service(
        lambda: service.activate_research_scope(
            version_id,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
        )
    )


def _call_service(operation: Callable[[], T]) -> T:
    """call service."""
    try:
        return operation()
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
