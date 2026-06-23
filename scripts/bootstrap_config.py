"""Bootstrap v0.2 versioned configuration from non-sensitive defaults and env secrets."""

from __future__ import annotations

import logging

from sqlalchemy import select

from margin.api.dependencies import get_provider_config_health_service
from margin.core.secret_store import SecretStore, SQLAlchemySecretRepository
from margin.data.db_models import SecurityMasterRow
from margin.settings import MarginSettings, get_settings
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)
from margin.strategy.bootstrap import (
    ProviderBootstrapSpec,
    StrategyBootstrapService,
)
from margin.strategy.models import ConfigLifecycle
from margin.strategy.repository import SQLAlchemyStrategyRepository
from margin.strategy.service import StrategyService
from margin.strategy.validator import ActivationError

logger = logging.getLogger(__name__)


def build_provider_specs(
    settings: MarginSettings,
) -> tuple[ProviderBootstrapSpec, ...]:
    """Return non-sensitive Provider definitions derived from settings."""
    specs: list[ProviderBootstrapSpec] = [
        ProviderBootstrapSpec(
            provider_name="akshare",
            provider_type="market_data",
            secret_required=False,
        ),
        ProviderBootstrapSpec(
            provider_name="tushare",
            provider_type="market_data",
            base_url=settings.tushare_http_url or "https://api.tushare.pro",
            non_sensitive_config={"allow_custom_base_url": True},
        ),
        ProviderBootstrapSpec(
            provider_name="tavily",
            provider_type="websearch",
            base_url="https://api.tavily.com/search",
            config_revision="v0.2.1",
        ),
        ProviderBootstrapSpec(
            provider_name="llm",
            provider_type="llm",
            base_url=(
                str(settings.llm_base_url)
                if settings.llm_base_url is not None
                else None
            ),
            model_name=settings.llm_model,
        ),
        ProviderBootstrapSpec(
            provider_name="embedding",
            provider_type="embedding",
            base_url=(
                str(settings.embedding_base_url)
                if settings.embedding_base_url is not None
                else None
            ),
            model_name=settings.embedding_model,
            non_sensitive_config={"dimension": settings.embedding_dimension},
        ),
    ]
    if settings.rerank_base_url is not None or settings.rerank_api_key is not None:
        specs.append(
            ProviderBootstrapSpec(
                provider_name="rerank",
                provider_type="rerank",
                base_url=(
                    str(settings.rerank_base_url)
                    if settings.rerank_base_url is not None
                    else None
                ),
                model_name=settings.rerank_model,
            )
        )
    return tuple(specs)


def main() -> int:
    """Create defaults, import configured secrets, health-check, and activate."""
    settings = get_settings()
    if settings.secret_master_key is None:
        raise RuntimeError("MARGIN_SECRET_MASTER_KEY is required for bootstrap")

    engine = create_database_engine(
        DatabaseSettings(
            url=str(settings.database_url),
            echo=settings.database_echo,
            pool_pre_ping=settings.database_pool_pre_ping,
        )
    )
    session_factory = create_session_factory(engine)
    repository = SQLAlchemyStrategyRepository(session_factory)
    service = StrategyService(repository=repository)
    secret_store = SecretStore(
        SQLAlchemySecretRepository(session_factory),
        master_key=settings.secret_master_key.get_secret_value(),
        key_version=settings.secret_key_version,
    )
    health_service = get_provider_config_health_service(repository, secret_store)
    bootstrap = StrategyBootstrapService(
        repository=repository,
        strategy_service=service,
        health_service=health_service,
    )
    specs = build_provider_specs(settings)
    members = _active_security_ids(session_factory)

    bootstrap.ensure_defaults(
        member_security_ids=members,
        providers=specs,
        required_provider_names=("tushare", "tavily", "llm", "embedding"),
    )
    for spec in specs:
        _import_and_activate_provider(
            spec=spec,
            settings=settings,
            repository=repository,
            service=service,
            secret_store=secret_store,
            health_service=health_service,
        )
    result = bootstrap.ensure_defaults(
        member_security_ids=members,
        providers=specs,
        required_provider_names=("tushare", "tavily", "llm", "embedding"),
    )
    logger.info(
        "strategy_bootstrap_completed",
        extra={
            "scope_version_id": result.scope_version_id,
            "provider_count": len(result.provider_version_ids),
            "missing_provider_names": result.missing_provider_names,
            "universe_member_count": len(members),
        },
    )
    engine.dispose()
    return 0


def _active_security_ids(session_factory) -> tuple[str, ...]:  # noqa: ANN001
    """Return currently visible stock security IDs for the ALL_A default."""
    with session_factory() as session:
        values = session.scalars(
            select(SecurityMasterRow.security_id)
            .where(SecurityMasterRow.system_to.is_(None))
            .where(SecurityMasterRow.security_type == "stock")
            .order_by(SecurityMasterRow.security_id)
        ).all()
    return tuple(values)


def _import_and_activate_provider(
    *,
    spec: ProviderBootstrapSpec,
    settings: MarginSettings,
    repository: SQLAlchemyStrategyRepository,
    service: StrategyService,
    secret_store: SecretStore,
    health_service,
) -> None:  # noqa: ANN001
    """Import one configured environment secret and activate after real health."""
    config = repository.get_provider_config(spec.version_id)
    if config is None or config.lifecycle is ConfigLifecycle.ACTIVE:
        return
    secret_value, secret_name = _provider_secret(settings, spec.provider_name)
    if spec.secret_required and secret_value is None:
        return
    if spec.secret_required and config.secret_version_id is None:
        service.write_provider_secret(
            provider_config_version_id=config.version_id,
            secret_name=secret_name,
            secret_value=secret_value or "",
            actor_id="bootstrap",
            idempotency_key=f"bootstrap-{config.version_id}-secret-v1",
            secret_store=secret_store,
        )
    try:
        service.activate_provider_config(
            config.version_id,
            health_service=health_service,
            actor_id="bootstrap",
            idempotency_key=f"bootstrap-{config.version_id}-activate-v1",
        )
    except ActivationError:
        logger.warning(
            "provider_bootstrap_health_failed",
            extra={
                "provider_name": config.provider_name,
                "provider_config_version_id": config.version_id,
            },
        )


def _provider_secret(
    settings: MarginSettings,
    provider_name: str,
) -> tuple[str | None, str]:
    """Return a plaintext secret only inside the trusted bootstrap boundary."""
    normalized = provider_name.strip().lower()
    if normalized == "tushare":
        return _secret_value(settings.tushare_token), "api_token"
    if normalized == "tavily":
        return _secret_value(settings.websearch_api_key), "api_key"
    if normalized == "llm":
        return _secret_value(settings.llm_api_key), "api_key"
    if normalized == "embedding":
        return _secret_value(settings.embedding_api_key), "api_key"
    if normalized == "rerank":
        return _secret_value(settings.rerank_api_key), "api_key"
    return None, "api_key"


def _secret_value(value) -> str | None:  # noqa: ANN001
    """Normalize a configured SecretStr without logging or serializing it."""
    if value is None:
        return None
    plaintext = value.get_secret_value().strip()
    return plaintext or None


if __name__ == "__main__":
    raise SystemExit(main())
