"""Runtime configuration zipper-table tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from margin.agent_runtime.quant_agent import CURRENT_QUANT_AGENT_ML_PROFILE
from margin.agent_runtime.step_definitions import load_scheduled_stock_analysis_flow
from margin.config_runtime.bootstrap import (
    DEFAULT_AGENT_FLOW_VERSION_ID,
    DEFAULT_QUANT_AGENT_PROFILE_VERSION_ID,
    RuntimeConfigBootstrapService,
)
from margin.config_runtime.models import (
    AgentFlowConfigVersion,
    ConfigReference,
    QuantAgentProfileConfigVersion,
)
from margin.config_runtime.repository import (
    ConfigAdminService,
    ConfigResolver,
    MemoryConfigRepository,
    SQLAlchemyConfigRepository,
)
from margin.storage.base import Base
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)


def test_memory_resolver_picks_agent_flow_by_decision_time() -> None:
    """Agent flow config versions are resolved PIT-safely from their own table.

    Returns:
        None: .
    """
    repository = MemoryConfigRepository()
    admin = ConfigAdminService(repository)
    resolver = ConfigResolver(repository)
    flow = load_scheduled_stock_analysis_flow()

    old = admin.publish_agent_flow(
        AgentFlowConfigVersion.from_flow(
            version_id="agent-flow-old",
            flow=flow.model_copy(update={"version": "v0.old"}),
            valid_from=_dt(2026, 1, 1),
            valid_to=_dt(2026, 7, 1),
            available_at=_dt(2026, 1, 1),
            change_reason="old config",
        )
    )
    new = admin.publish_agent_flow(
        AgentFlowConfigVersion.from_flow(
            version_id="agent-flow-new",
            flow=flow.model_copy(update={"version": "v0.new"}),
            valid_from=_dt(2026, 7, 1),
            available_at=_dt(2026, 7, 1),
            supersedes_version_id=old.version_id,
            change_reason="new config",
        )
    )

    before_cutover = resolver.resolve_agent_flow(
        flow_id="scheduled_stock_analysis",
        decision_at=_dt(2026, 6, 30, 23),
    )
    after_cutover = resolver.resolve_agent_flow(
        flow_id="scheduled_stock_analysis",
        decision_at=_dt(2026, 7, 8),
    )

    assert before_cutover.version_id == "agent-flow-old"
    assert before_cutover.to_flow().version == "v0.old"
    assert after_cutover.version_id == "agent-flow-new"
    assert after_cutover.to_flow().version == "v0.new"
    assert after_cutover.payload_hash.startswith("sha256:")
    assert new.supersedes_version_id == old.version_id


def test_quant_profile_and_resolution_snapshot_store_references_only() -> None:
    """Resolved runtime snapshots record version lineage, not copied config bodies.

    Returns:
        None: .
    """
    repository = MemoryConfigRepository()
    admin = ConfigAdminService(repository)
    resolver = ConfigResolver(repository)

    profile_version = admin.publish_quant_agent_profile(
        QuantAgentProfileConfigVersion.from_profile(
            version_id="quant-profile-v1",
            profile_key="scheduled_stock_analysis",
            profile=CURRENT_QUANT_AGENT_ML_PROFILE,
            valid_from=_dt(2026, 1, 1),
            available_at=_dt(2026, 1, 1),
            change_reason="default ML profile",
        )
    )
    resolved = resolver.resolve_quant_agent_profile(
        profile_key="scheduled_stock_analysis",
        decision_at=_dt(2026, 7, 8),
    )

    snapshot = resolver.create_resolution_snapshot(
        run_id="ar_sched_20260708_0830",
        decision_at=_dt(2026, 7, 8, 0, 30),
        references=(ConfigReference.from_version("quant_agent_profile", resolved),),
    )

    assert resolved.version_id == profile_version.version_id
    assert resolved.to_profile().profile_id == CURRENT_QUANT_AGENT_ML_PROFILE.profile_id
    assert snapshot.entries[0].domain == "quant_agent_profile"
    assert snapshot.entries[0].version_id == "quant-profile-v1"
    assert snapshot.entries[0].payload_hash == profile_version.payload_hash
    assert "payload" not in snapshot.entries[0].model_dump()


def test_runtime_config_bootstrap_is_idempotent() -> None:
    """Bootstrap can run repeatedly without overwriting active config versions.

    Returns:
        None: .
    """
    repository = MemoryConfigRepository()
    admin = ConfigAdminService(repository)
    resolver = ConfigResolver(repository)
    bootstrap = RuntimeConfigBootstrapService(
        admin_service=admin,
        resolver=resolver,
    )

    first = bootstrap.ensure_defaults()
    second = bootstrap.ensure_defaults()

    assert first == second
    assert first == (
        DEFAULT_AGENT_FLOW_VERSION_ID,
        DEFAULT_QUANT_AGENT_PROFILE_VERSION_ID,
    )


def test_sqlalchemy_repository_round_trips_domain_config_tables(
    database_url: str,
) -> None:
    """Domain-specific config tables persist flow/profile versions and snapshots.

    Args:
        database_url: str: .

    Returns:
        None: .
    """
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    repository = SQLAlchemyConfigRepository(session_factory)
    admin = ConfigAdminService(repository)
    owner_id = f"config-test-{uuid4().hex[:8]}"
    resolver = ConfigResolver(repository, owner_id=owner_id)

    flow_version = admin.publish_agent_flow(
        AgentFlowConfigVersion.from_flow(
            version_id=f"agent-flow-pg-{owner_id}",
            flow=load_scheduled_stock_analysis_flow(),
            owner_id=owner_id,
            valid_from=_dt(2026, 7, 1),
            available_at=_dt(2026, 7, 1),
            change_reason="postgres flow",
        )
    )
    profile_version = admin.publish_quant_agent_profile(
        QuantAgentProfileConfigVersion.from_profile(
            version_id=f"quant-profile-pg-{owner_id}",
            profile_key="scheduled_stock_analysis",
            profile=CURRENT_QUANT_AGENT_ML_PROFILE,
            owner_id=owner_id,
            valid_from=_dt(2026, 7, 1),
            available_at=_dt(2026, 7, 1),
            change_reason="postgres profile",
        )
    )
    snapshot = resolver.create_resolution_snapshot(
        run_id="ar_sched_pg",
        decision_at=_dt(2026, 7, 8),
        references=(
            ConfigReference.from_version("agent_flow", flow_version),
            ConfigReference.from_version("quant_agent_profile", profile_version),
        ),
    )

    fresh = SQLAlchemyConfigRepository(session_factory)
    assert (
        fresh.resolve_agent_flow(
            flow_id="scheduled_stock_analysis",
            owner_id=owner_id,
            environment="development",
            decision_at=_dt(2026, 7, 8),
        ).version_id
        == f"agent-flow-pg-{owner_id}"
    )
    assert (
        fresh.get_resolution_snapshot(snapshot.snapshot_id).entries[1].version_id
        == f"quant-profile-pg-{owner_id}"
    )
    engine.dispose()


def _dt(
    year: int,
    month: int,
    day: int,
    hour: int = 0,
    minute: int = 0,
) -> datetime:
    """Return a UTC datetime.

    Args:
        year: int: .
        month: int: .
        day: int: .
        hour: int: .
        minute: int: .

    Returns:
        datetime: .
    """
    return datetime(year, month, day, hour, minute, tzinfo=UTC)
