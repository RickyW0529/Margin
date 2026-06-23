"""PostgreSQL strategy repository integration tests."""

from __future__ import annotations

from margin.storage.base import Base
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)
from margin.strategy.db_models import StrategyProfileRow, StrategyVersionRow
from margin.strategy.models import (
    PromptLayer,
    StrategyConfig,
    StrategyProfile,
    StrategySandboxResult,
    StrategyState,
    StrategyVersion,
)
from margin.strategy.repository import SQLAlchemyStrategyRepository


def test_postgres_strategy_repository_round_trips_prompt_layers(database_url):
    """Strategy versions must keep prompt layers across fresh repository instances."""
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    with session_factory.begin() as session:
        session.query(StrategyVersionRow).delete()
        session.query(StrategyProfileRow).delete()

    repo = SQLAlchemyStrategyRepository(session_factory)
    version = StrategyVersion(
        strategy_id="st_pg_strategy",
        version_id="sv_pg_strategy",
        name="Value Quality",
        config=StrategyConfig(),
        prompt_layers=(
            PromptLayer(
                layer="system_guardrail",
                content="cite evidence",
                editable=False,
            ),
            PromptLayer(
                layer="user_custom",
                content="focus on ROE",
                editable=True,
            ),
        ),
        prompt_version="1.0.0",
    )
    profile = StrategyProfile(
        strategy_id=version.strategy_id,
        owner_id="user_1",
        name="Persistent Strategy",
        versions=(version,),
    )

    try:
        repo.add_profile(profile)
        fresh = SQLAlchemyStrategyRepository(session_factory)

        stored = fresh.get_profile(profile.strategy_id)

        assert stored == profile
        assert stored.versions[0].prompt_layers == version.prompt_layers
    finally:
        with session_factory.begin() as session:
            session.query(StrategyVersionRow).delete()
            session.query(StrategyProfileRow).delete()
        engine.dispose()


def test_postgres_strategy_repository_updates_existing_version_lifecycle_state(
    database_url,
):
    """Lifecycle state and sandbox results must persist for existing versions."""
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    with session_factory.begin() as session:
        session.query(StrategyVersionRow).delete()
        session.query(StrategyProfileRow).delete()

    repo = SQLAlchemyStrategyRepository(session_factory)
    version = StrategyVersion(
        strategy_id="st_pg_lifecycle",
        version_id="sv_pg_lifecycle",
        name="Lifecycle",
        config=StrategyConfig(),
    )
    profile = StrategyProfile(
        strategy_id=version.strategy_id,
        owner_id="user_1",
        name="Lifecycle Strategy",
        versions=(version,),
    )

    try:
        repo.add_profile(profile)
        updated_version = version.model_copy(
            update={
                "state": StrategyState.BACKTESTING,
                "sandbox_result": StrategySandboxResult(
                    validation_ok=True,
                    sample_run_ok=True,
                    backtest_ok=True,
                    data_leak_ok=True,
                    cost_ok=True,
                    preview_ok=True,
                ),
            }
        )
        repo.update_profile(profile.model_copy(update={"versions": (updated_version,)}))

        stored = SQLAlchemyStrategyRepository(session_factory).get_profile(
            profile.strategy_id
        )

        assert stored.versions[0].state == StrategyState.BACKTESTING
        assert stored.versions[0].sandbox_result.validation_ok is True
    finally:
        with session_factory.begin() as session:
            session.query(StrategyVersionRow).delete()
            session.query(StrategyProfileRow).delete()
        engine.dispose()
