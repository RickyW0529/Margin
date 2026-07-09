"""Persistence tests for v1 Agent PromptBundle system."""

from __future__ import annotations

from margin.agents.prompts.bundles import PromptBundle, PromptTemplate
from margin.agents.prompts.db_models import (
    LLMCallAuditRow,
    PromptBundleRow,
    PromptRenderHistoryRow,
    PromptTemplateRow,
)
from margin.agents.prompts.render import PromptRenderer
from margin.agents.prompts.repository import LLMCallAuditEntry, SQLAlchemyPromptRepository
from margin.storage.base import Base
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)


def test_sqlalchemy_prompt_repository_round_trips_active_bundle(database_url: str) -> None:
    """PromptRepository should persist templates and active bundle metadata."""
    repository = _repository(database_url)
    bundle = _bundle()

    repository.save_bundle(bundle, active=True)

    stored = repository.get_active_bundle("main")
    assert stored == bundle


def test_prompt_renderer_persists_render_history_without_raw_prompt_text(
    database_url: str,
) -> None:
    """PromptRenderer should persist render hashes without storing full prompt text."""
    repository = _repository(database_url)
    renderer = PromptRenderer(render_history_repository=repository)

    record = renderer.render_bundle(
        _bundle(),
        run_id="run_prompt_sql",
        task_id="task_prompt_sql",
        agent_name="MainAgent",
        variables={"context_pack": '{"facts":[]}'},
    )

    stored = repository.get_render_record(record.render_id)
    assert stored is not None
    assert stored.render_id == record.render_id
    assert stored.prompt_hash == record.prompt_hash
    assert stored.variables_hash == record.variables_hash
    assert not hasattr(stored, "rendered_messages")


def test_prompt_repository_persists_llm_call_audit_without_payloads(
    database_url: str,
) -> None:
    """LLM audit records should keep metadata without raw prompt or response payloads."""
    repository = _repository(database_url)
    started_at = _bundle().created_at

    repository.record_llm_call(
        LLMCallAuditEntry(
            llm_call_id="llm_prompt_sql",
            run_id="run_prompt_sql",
            task_id="task_prompt_sql",
            agent_name="MainAgent",
            provider_name="deterministic",
            model_name="local-test",
            prompt_render_id="render_prompt_sql",
            input_token_count=12,
            output_token_count=8,
            temperature=0,
            status="succeeded",
            error_code=None,
            started_at=started_at,
            finished_at=started_at,
        )
    )

    stored = repository.get_llm_call_record("llm_prompt_sql")
    assert stored is not None
    assert stored.llm_call_id == "llm_prompt_sql"
    assert stored.prompt_render_id == "render_prompt_sql"
    assert stored.input_token_count == 12
    assert not hasattr(stored, "prompt_text")
    assert not hasattr(stored, "response_payload")


def _bundle() -> PromptBundle:
    """Return a deterministic PromptBundle."""
    return PromptBundle(
        prompt_bundle_id="bundle_sql_main",
        version="v1",
        target_agent_type="main",
        templates=(
            PromptTemplate(
                prompt_id="main_system_sql",
                version="v1",
                role="system",
                template_text="Use only CONTEXT_PACK: {{context_pack}}. Use ToolGateway only.",
                allowed_variables=("context_pack",),
                output_schema_ref="MainPlanSchema",
                safety_tags=("context_pack_only", "toolgateway_only"),
            ),
        ),
        model_profile_ref="local-test",
        max_output_tokens=1024,
        temperature=0,
    )


def _repository(database_url: str) -> SQLAlchemyPromptRepository:
    """Create a repository against the integration-test database."""
    engine = create_database_engine(DatabaseSettings(url=database_url))
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS prompt")
    Base.metadata.drop_all(engine, tables=_prompt_tables(), checkfirst=True)
    Base.metadata.create_all(engine)
    return SQLAlchemyPromptRepository(create_session_factory(engine))


def _prompt_tables() -> list:
    """Return prompt tables in dependency-safe drop order."""
    return [
        LLMCallAuditRow.__table__,
        PromptRenderHistoryRow.__table__,
        PromptBundleRow.__table__,
        PromptTemplateRow.__table__,
    ]
