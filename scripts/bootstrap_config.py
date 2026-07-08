"""Bootstrap v0.3 versioned configuration from non-sensitive defaults."""

from __future__ import annotations

import logging

from sqlalchemy import bindparam, text

from margin.settings import MarginSettings, get_settings
from margin.sql.data_queries import active_stock_security_ids
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)
from margin.strategy.bootstrap import (
    DEFAULT_INDEX_UNIVERSES,
    ProviderBootstrapSpec,
    StrategyBootstrapService,
)
from margin.strategy.repository import SQLAlchemyStrategyRepository
from margin.strategy.service import StrategyService

logger = logging.getLogger(__name__)


def build_provider_specs(
    _settings: MarginSettings,
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
            base_url="https://api.tushare.pro",
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
        ),
        ProviderBootstrapSpec(
            provider_name="embedding",
            provider_type="embedding",
            non_sensitive_config={"dimension": 1536},
        ),
        ProviderBootstrapSpec(
            provider_name="rerank",
            provider_type="rerank",
        ),
    ]
    return tuple(specs)


def main() -> int:
    """Create non-sensitive defaults; provider secrets are configured in the UI."""
    settings = get_settings()
    if settings.secret_master_key is None:
        raise RuntimeError("MARGIN_SECRET_MASTER_KEY is required for bootstrap")

    engine = create_database_engine(DatabaseSettings.from_settings(settings))
    session_factory = create_session_factory(engine)
    repository = SQLAlchemyStrategyRepository(session_factory)
    service = StrategyService(repository=repository)
    bootstrap = StrategyBootstrapService(
        repository=repository,
        strategy_service=service,
    )
    specs = build_provider_specs(settings)
    members = _active_security_ids(session_factory)

    result = bootstrap.ensure_defaults(
        member_security_ids=members,
        providers=specs,
        required_provider_names=("tushare", "tavily", "llm", "embedding"),
    )
    index_members_by_code = _latest_index_members_by_code(session_factory)
    index_universe_ids = bootstrap.ensure_default_index_universes(
        index_members_by_code=index_members_by_code,
    )
    logger.info(
        "strategy_bootstrap_completed",
        extra={
            "scope_version_id": result.scope_version_id,
            "provider_count": len(result.provider_version_ids),
            "missing_provider_names": result.missing_provider_names,
            "universe_member_count": len(members),
            "index_universe_ids": index_universe_ids,
        },
    )
    engine.dispose()
    return 0


def _active_security_ids(session_factory) -> tuple[str, ...]:  # noqa: ANN001
    """Return currently visible stock security IDs for the ALL_A default."""
    with session_factory() as session:
        values = session.scalars(
            active_stock_security_ids()
        ).all()
    return tuple(values)


def _latest_index_members_by_code(session_factory) -> dict[str, tuple[str, ...]]:  # noqa: ANN001
    """Return latest CSI300/CSI500 members from Tushare raw index weights."""
    index_codes = {
        str(spec["index_code"]): universe_code
        for universe_code, spec in DEFAULT_INDEX_UNIVERSES.items()
    }
    statement = text(
        """
        with latest as (
            select raw_payload->>'index_code' as index_code,
                   max(raw_payload->>'trade_date') as trade_date
            from source_tushare.ts_index_weight
            where raw_payload->>'index_code' in :index_codes
            group by raw_payload->>'index_code'
        )
        select l.index_code as index_code,
               s.raw_payload->>'con_code' as security_id
        from latest l
        join source_tushare.ts_index_weight s
          on s.raw_payload->>'index_code' = l.index_code
         and s.raw_payload->>'trade_date' = l.trade_date
        where s.raw_payload->>'con_code' is not null
        order by l.index_code, security_id
        """
    ).bindparams(bindparam("index_codes", expanding=True))
    members: dict[str, list[str]] = {
        universe_code: [] for universe_code in index_codes.values()
    }
    with session_factory() as session:
        rows = session.execute(statement, {"index_codes": tuple(index_codes)}).mappings()
        for row in rows:
            universe_code = index_codes.get(str(row["index_code"]))
            security_id = row["security_id"]
            if universe_code is not None and isinstance(security_id, str):
                members[universe_code].append(security_id)
    return {
        universe_code: tuple(sorted(set(values)))
        for universe_code, values in members.items()
        if values
    }


if __name__ == "__main__":
    raise SystemExit(main())
