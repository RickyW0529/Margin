"""v0.2 versioned strategy configuration API."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, TypeVar

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
from margin.strategy.provider_router import enrich_provider_config_metadata
from margin.strategy.service import StrategyService
from margin.valuation_discovery.quant.pool_defaults import quant_strategy_defaults_payload

router = APIRouter(prefix="/api/v1", tags=["strategy-config-v0.2"])
T = TypeVar("T")


class WriteProviderSecretRequest(BaseModel):
    """Write-only provider secret request.

    Attributes:
        secret_name: Name of the secret to write.
        secret_value: Plaintext value to encrypt and store.
    """

    secret_name: str
    secret_value: str


class SecretMetadataResponse(BaseModel):
    """Safe provider secret metadata response.

    Attributes:
        configured: Whether the secret is currently active.
        last_four: Last four characters of the plaintext for display.
        version_id: Unique identifier of the secret version.
        status: Lifecycle status (e.g. ``active``, ``deactivated``).
        updated_at: UTC timestamp of the last status change.
        provider_name: Name of the provider the secret belongs to.
        secret_name: Name of the secret within the provider.
    """

    configured: bool
    last_four: str
    version_id: str
    status: str
    updated_at: datetime
    provider_name: str
    secret_name: str

    @classmethod
    def from_metadata(cls, metadata: SecretMetadata) -> SecretMetadataResponse:
        """Build a response without plaintext, ciphertext, nonce, or key material.

        Args:
            metadata: Internal secret metadata to project into a safe response.

        Returns:
            A SecretMetadataResponse with no sensitive material exposed.
        """
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
    """Safe provider config summary for the settings UI.

    Attributes:
        version_id: Unique identifier of the provider config version.
        provider_name: Name of the provider.
        provider_type: Capability category of the provider.
        enabled: Whether the provider config is enabled.
        lifecycle: Lifecycle status (e.g. ``draft``, ``active``, ``deprecated``).
        base_url: Optional base URL for the provider API.
    model_name: Optional model name used by the provider.
        provider_category: Normalized UI/runtime category.
        detected_provider: Provider id detected from URL within the category.
        detected_label: Short label safe to display next to the category title.
        is_custom_provider: Whether URL detection fell back to Custom.
        secret_metadata: Optional safe metadata for the bound secret.
    """

    version_id: str
    provider_name: str
    provider_type: str
    enabled: bool
    lifecycle: str
    base_url: str | None
    model_name: str | None
    provider_category: str
    detected_provider: str
    detected_label: str
    is_custom_provider: bool
    secret_metadata: SecretMetadataResponse | None

    @classmethod
    def from_version(
        cls,
        version: ProviderConfigVersion,
        secret_store: SecretStore | None,
    ) -> ProviderConfigResponse:
        """Build a safe response with optional write-only secret metadata.

        Args:
            version: Provider config version to render.
            secret_store: Optional secret store for resolving bound secret
                metadata. When None, secret_metadata is omitted.

        Returns:
            A ProviderConfigResponse with safe fields and optional secret
            metadata.
        """
        secret_metadata = None
        if version.secret_version_id and secret_store is not None:
            secret_metadata = SecretMetadataResponse.from_metadata(
                secret_store.metadata(version.secret_version_id)
            )
        router_metadata = enrich_provider_config_metadata(version)
        return cls(
            version_id=version.version_id,
            provider_name=version.provider_name,
            provider_type=version.provider_type,
            enabled=version.enabled,
            lifecycle=version.lifecycle.value,
            base_url=version.base_url,
            model_name=version.model_name,
            provider_category=str(router_metadata["provider_category"]),
            detected_provider=str(router_metadata["detected_provider"]),
            detected_label=str(router_metadata["detected_label"]),
            is_custom_provider=bool(router_metadata["is_custom_provider"]),
            secret_metadata=secret_metadata,
        )


@router.get("/provider-configs")
def list_provider_configs(
    owner_id: str = "local-admin",
    service: StrategyService = Depends(get_strategy_service),
    secret_store: SecretStore | None = Depends(get_optional_secret_store),
) -> list[ProviderConfigResponse]:
    """List provider config versions without returning secret contents.

    Args:
        owner_id: Identifier of the owner whose configs should be listed.
        service: Strategy service used to query provider configs.
        secret_store: Optional secret store for resolving secret metadata.

    Returns:
        A list of ProviderConfigResponse objects with safe metadata.
    """
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
    """Create an append-only provider configuration version.

    Args:
        version: Provider config version to create.
        actor_id: Authenticated actor identifier.
        idempotency_key: Idempotency key for the mutation.
        service: Strategy service used to create the version.

    Returns:
        The created ProviderConfigVersion.
    """
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
    """Encrypt and bind a provider secret, returning metadata only.

    Args:
        version_id: Provider config version to bind the secret to.
        request: Write-only secret request containing the secret name and value.
        actor_id: Authenticated actor identifier.
        idempotency_key: Idempotency key for the mutation.
        service: Strategy service used to write the secret.
        secret_store: Encrypted secret store for persisting the secret.

    Returns:
        SecretMetadataResponse with safe metadata for the stored secret.
    """
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
    """Run a read-only health check for a frozen provider config version.

    Args:
        version_id: Provider config version to test.
        _actor_id: Authenticated actor identifier (unused).
        _idempotency_key: Idempotency key for the mutation (unused).
        health_service: Provider health service used to run the check.

    Returns:
        ProviderHealth result of the health check.
    """
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
    """Activate a provider config version.

    Args:
        version_id: Provider config version to activate.
        actor_id: Authenticated actor identifier.
        idempotency_key: Idempotency key for the mutation.
        service: Strategy service used to activate the version.
        health_service: Provider health service used to validate the connection.

    Returns:
        The activated ProviderConfigVersion.
    """
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
    """List universe definition versions.

    Args:
        owner_id: Identifier of the owner whose universe configs should be listed.
        service: Strategy service used to query universe definitions.

    Returns:
        A list of UniverseDefinitionVersion objects.
    """
    return service.list_universe_definitions(owner_id)


@router.post("/universe-configs")
def create_universe_config(
    version: UniverseDefinitionVersion,
    actor_id: str = Depends(require_local_admin),
    idempotency_key: str = Depends(require_idempotency_key),
    service: StrategyService = Depends(get_strategy_service),
) -> UniverseDefinitionVersion:
    """Create an append-only universe definition version.

    Args:
        version: Universe definition version to create.
        actor_id: Authenticated actor identifier.
        idempotency_key: Idempotency key for the mutation.
        service: Strategy service used to create the version.

    Returns:
        The created UniverseDefinitionVersion.
    """
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
    """Activate a universe definition version.

    Args:
        version_id: Universe definition version to activate.
        actor_id: Authenticated actor identifier.
        idempotency_key: Idempotency key for the mutation.
        service: Strategy service used to activate the version.

    Returns:
        The activated UniverseDefinitionVersion.
    """
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
    """List indicator view versions.

    Args:
        owner_id: Identifier of the owner whose indicator views should be listed.
        service: Strategy service used to query indicator views.

    Returns:
        A list of IndicatorViewVersion objects.
    """
    return service.list_indicator_views(owner_id)


@router.post("/indicator-views")
def create_indicator_view(
    version: IndicatorViewVersion,
    actor_id: str = Depends(require_local_admin),
    idempotency_key: str = Depends(require_idempotency_key),
    service: StrategyService = Depends(get_strategy_service),
) -> IndicatorViewVersion:
    """Create an append-only indicator view version.

    Args:
        version: Indicator view version to create.
        actor_id: Authenticated actor identifier.
        idempotency_key: Idempotency key for the mutation.
        service: Strategy service used to create the version.

    Returns:
        The created IndicatorViewVersion.
    """
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
    """Activate an indicator view version.

    Args:
        version_id: Indicator view version to activate.
        actor_id: Authenticated actor identifier.
        idempotency_key: Idempotency key for the mutation.
        service: Strategy service used to activate the version.

    Returns:
        The activated IndicatorViewVersion.
    """
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
    """List quant feature set versions.

    Args:
        owner_id: Identifier of the owner whose quant feature sets should be listed.
        service: Strategy service used to query quant feature sets.

    Returns:
        A list of QuantFeatureSetVersion objects.
    """
    return service.list_quant_feature_sets(owner_id)


@router.post("/quant-feature-sets")
def create_quant_feature_set(
    version: QuantFeatureSetVersion,
    actor_id: str = Depends(require_local_admin),
    idempotency_key: str = Depends(require_idempotency_key),
    service: StrategyService = Depends(get_strategy_service),
) -> QuantFeatureSetVersion:
    """Create an append-only quant feature set version.

    Args:
        version: Quant feature set version to create.
        actor_id: Authenticated actor identifier.
        idempotency_key: Idempotency key for the mutation.
        service: Strategy service used to create the version.

    Returns:
        The created QuantFeatureSetVersion.
    """
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
    """Activate a quant feature set version.

    Args:
        version_id: Quant feature set version to activate.
        actor_id: Authenticated actor identifier.
        idempotency_key: Idempotency key for the mutation.
        service: Strategy service used to activate the version.

    Returns:
        The activated QuantFeatureSetVersion.
    """
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
    """List quant strategy versions.

    Args:
        owner_id: Identifier of the owner whose quant strategies should be listed.
        service: Strategy service used to query quant strategies.

    Returns:
        A list of QuantStrategyVersion objects.
    """
    return service.list_quant_strategies(owner_id)


@router.get("/quant-strategy-defaults")
def get_quant_strategy_defaults() -> dict[str, Any]:
    """Return built-in monthly manual strategy presets for supported pools.

    Returns:
        A dictionary mapping pool names to their default strategy payloads.
    """
    return quant_strategy_defaults_payload()


@router.post("/quant-strategies")
def create_quant_strategy(
    version: QuantStrategyVersion,
    actor_id: str = Depends(require_local_admin),
    idempotency_key: str = Depends(require_idempotency_key),
    service: StrategyService = Depends(get_strategy_service),
) -> QuantStrategyVersion:
    """Create an append-only quant strategy version.

    Args:
        version: Quant strategy version to create.
        actor_id: Authenticated actor identifier.
        idempotency_key: Idempotency key for the mutation.
        service: Strategy service used to create the version.

    Returns:
        The created QuantStrategyVersion.
    """
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
    """Activate a calibrated quant strategy version.

    Args:
        version_id: Quant strategy version to activate.
        actor_id: Authenticated actor identifier.
        idempotency_key: Idempotency key for the mutation.
        service: Strategy service used to activate the version.

    Returns:
        The activated QuantStrategyVersion.
    """
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
    """List user style prompt versions.

    Args:
        owner_id: Identifier of the owner whose style prompts should be listed.
        service: Strategy service used to query style prompts.

    Returns:
        A list of UserStylePromptVersion objects.
    """
    return service.list_user_style_prompts(owner_id)


@router.post("/style-prompts")
def create_style_prompt(
    version: UserStylePromptVersion,
    actor_id: str = Depends(require_local_admin),
    idempotency_key: str = Depends(require_idempotency_key),
    service: StrategyService = Depends(get_strategy_service),
) -> UserStylePromptVersion:
    """Create an append-only user style prompt version.

    Args:
        version: User style prompt version to create.
        actor_id: Authenticated actor identifier.
        idempotency_key: Idempotency key for the mutation.
        service: Strategy service used to create the version.

    Returns:
        The created UserStylePromptVersion.
    """
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
    """Activate a style prompt after protected-boundary validation.

    Args:
        version_id: User style prompt version to activate.
        actor_id: Authenticated actor identifier.
        idempotency_key: Idempotency key for the mutation.
        service: Strategy service used to activate the version.

    Returns:
        The activated UserStylePromptVersion.
    """
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
    """List frozen research scope versions.

    Args:
        owner_id: Identifier of the owner whose research scopes should be listed.
        service: Strategy service used to query research scopes.

    Returns:
        A list of ResearchScopeVersion objects.
    """
    return service.list_research_scopes(owner_id)


@router.post("/research-scopes")
def create_research_scope(
    version: ResearchScopeVersion,
    actor_id: str = Depends(require_local_admin),
    idempotency_key: str = Depends(require_idempotency_key),
    service: StrategyService = Depends(get_strategy_service),
) -> ResearchScopeVersion:
    """Create an append-only frozen research scope version.

    Args:
        version: Research scope version to create.
        actor_id: Authenticated actor identifier.
        idempotency_key: Idempotency key for the mutation.
        service: Strategy service used to create the version.

    Returns:
        The created ResearchScopeVersion.
    """
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
    """Activate a validated frozen research scope version.

    Args:
        version_id: Research scope version to activate.
        actor_id: Authenticated actor identifier.
        idempotency_key: Idempotency key for the mutation.
        service: Strategy service used to activate the version.

    Returns:
        The activated ResearchScopeVersion.
    """
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
