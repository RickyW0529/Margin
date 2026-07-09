"""Repositories for v1 Agent PromptBundle persistence."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from margin.agents.prompts.bundles import PromptBundle, PromptTemplate
from margin.agents.prompts.db_models import (
    LLMCallAuditRow,
    PromptBundleRow,
    PromptRenderHistoryRow,
    PromptTemplateRow,
)
from margin.agents.prompts.render import PromptRenderRecord


@dataclass(frozen=True)
class PromptRenderHistoryRecord:
    """Persisted prompt render metadata without raw rendered text."""

    render_id: str
    run_id: str
    task_id: str | None
    agent_name: str
    prompt_bundle_id: str
    prompt_hash: str
    variables_hash: str
    rendered_at: datetime


@dataclass(frozen=True)
class LLMCallAuditEntry:
    """Persisted LLM call metadata linked to a prompt render."""

    llm_call_id: str
    run_id: str
    task_id: str | None
    agent_name: str
    provider_name: str
    model_name: str
    prompt_render_id: str
    input_token_count: int | None
    output_token_count: int | None
    temperature: float | None
    status: str
    error_code: str | None
    started_at: datetime
    finished_at: datetime | None


class PromptRenderHistoryRepository(Protocol):
    """Persistence boundary for prompt render history."""

    def record_render(self, record: PromptRenderRecord) -> None:
        """Persist prompt render metadata."""


class SQLAlchemyPromptRepository:
    """SQLAlchemy-backed repository for PromptBundle and render history."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        """Initialize with a SQLAlchemy session factory."""
        self._session_factory = session_factory

    def save_bundle(self, bundle: PromptBundle, *, active: bool = False) -> None:
        """Persist a PromptBundle and all templates.

        Args:
            bundle: PromptBundle to save.
            active: Whether to mark it active for its target agent type.
        """
        with self._session_factory() as session, session.begin():
            for template in bundle.templates:
                current_template = session.get(
                    PromptTemplateRow,
                    {"prompt_id": template.prompt_id, "version": template.version},
                )
                template_row = _template_row(template)
                if current_template is None:
                    session.add(template_row)
                elif _template_payload(current_template) != template:
                    raise ValueError(
                        f"prompt template '{template.prompt_id}:{template.version}' is immutable"
                    )
            current_bundle = session.get(PromptBundleRow, bundle.prompt_bundle_id)
            bundle_row = _bundle_row(bundle, active=active)
            if current_bundle is None:
                if active:
                    session.execute(
                        update(PromptBundleRow)
                        .where(PromptBundleRow.target_agent_type == bundle.target_agent_type)
                        .values(is_active=False)
                    )
                session.add(bundle_row)
                return
            if _bundle_payload(session, current_bundle) != bundle:
                raise ValueError(f"prompt bundle '{bundle.prompt_bundle_id}' is immutable")
            if active and not current_bundle.is_active:
                session.execute(
                    update(PromptBundleRow)
                    .where(PromptBundleRow.target_agent_type == bundle.target_agent_type)
                    .values(is_active=False)
                )
                current_bundle.is_active = True

    def get_active_bundle(self, target_agent_type: str) -> PromptBundle:
        """Return the active PromptBundle for an agent type."""
        with self._session_factory() as session:
            row = session.scalars(
                select(PromptBundleRow).where(
                    PromptBundleRow.target_agent_type == target_agent_type,
                    PromptBundleRow.is_active.is_(True),
                )
            ).first()
            if row is None:
                raise KeyError(f"active prompt bundle not found: {target_agent_type}")
            return _bundle_payload(session, row)

    def record_render(self, record: PromptRenderRecord) -> None:
        """Persist prompt render metadata without raw rendered content."""
        with self._session_factory() as session, session.begin():
            current = session.get(PromptRenderHistoryRow, record.render_id)
            if current is not None:
                return
            session.add(
                PromptRenderHistoryRow(
                    render_id=record.render_id,
                    run_id=record.run_id,
                    task_id=record.task_id,
                    agent_name=record.agent_name,
                    prompt_bundle_id=record.prompt_bundle_id,
                    prompt_hash=record.prompt_hash,
                    variables_hash=record.variables_hash,
                    rendered_at=record.rendered_at,
                )
            )

    def get_render_record(self, render_id: str) -> PromptRenderHistoryRecord | None:
        """Return prompt render metadata by id."""
        with self._session_factory() as session:
            row = session.get(PromptRenderHistoryRow, render_id)
            if row is None:
                return None
            return PromptRenderHistoryRecord(
                render_id=row.render_id,
                run_id=row.run_id,
                task_id=row.task_id,
                agent_name=row.agent_name,
                prompt_bundle_id=row.prompt_bundle_id,
                prompt_hash=row.prompt_hash,
                variables_hash=row.variables_hash,
                rendered_at=row.rendered_at,
            )

    def record_llm_call(self, record: LLMCallAuditEntry) -> None:
        """Persist hash-safe LLM call audit metadata."""
        with self._session_factory() as session, session.begin():
            current = session.get(LLMCallAuditRow, record.llm_call_id)
            if current is None:
                session.add(_llm_call_row(record))
                return
            if _llm_call_payload(current) != record:
                raise ValueError(f"LLM call audit '{record.llm_call_id}' is immutable")

    def get_llm_call_record(self, llm_call_id: str) -> LLMCallAuditEntry | None:
        """Return LLM call audit metadata by id."""
        with self._session_factory() as session:
            row = session.get(LLMCallAuditRow, llm_call_id)
            return _llm_call_payload(row) if row is not None else None


def _template_row(template: PromptTemplate) -> PromptTemplateRow:
    """Convert a PromptTemplate to an ORM row."""
    return PromptTemplateRow(
        prompt_id=template.prompt_id,
        version=template.version,
        role=template.role,
        template_text=template.template_text,
        allowed_variables=list(template.allowed_variables),
        output_schema_ref=template.output_schema_ref,
        safety_tags=list(template.safety_tags),
        created_at=datetime.now(UTC),
    )


def _template_payload(row: PromptTemplateRow) -> PromptTemplate:
    """Convert a PromptTemplate row to a model."""
    return PromptTemplate(
        prompt_id=row.prompt_id,
        version=row.version,
        role=row.role,
        template_text=row.template_text,
        allowed_variables=tuple(row.allowed_variables),
        output_schema_ref=row.output_schema_ref,
        safety_tags=tuple(row.safety_tags),
    )


def _bundle_row(bundle: PromptBundle, *, active: bool) -> PromptBundleRow:
    """Convert a PromptBundle to an ORM row."""
    return PromptBundleRow(
        prompt_bundle_id=bundle.prompt_bundle_id,
        version=bundle.version,
        target_agent_type=bundle.target_agent_type,
        template_refs=[
            {"prompt_id": template.prompt_id, "version": template.version}
            for template in bundle.templates
        ],
        model_profile_ref=bundle.model_profile_ref,
        max_output_tokens=bundle.max_output_tokens,
        temperature=bundle.temperature,
        is_active=active,
        created_at=bundle.created_at,
    )


def _bundle_payload(session: Session, row: PromptBundleRow) -> PromptBundle:
    """Convert a PromptBundle row and template refs to a model."""
    templates: list[PromptTemplate] = []
    for template_ref in row.template_refs:
        template_row = session.get(
            PromptTemplateRow,
            {
                "prompt_id": template_ref["prompt_id"],
                "version": template_ref["version"],
            },
        )
        if template_row is None:
            raise KeyError(
                f"prompt template not found: {template_ref['prompt_id']}:{template_ref['version']}"
            )
        templates.append(_template_payload(template_row))
    return PromptBundle(
        prompt_bundle_id=row.prompt_bundle_id,
        version=row.version,
        target_agent_type=row.target_agent_type,
        templates=tuple(templates),
        model_profile_ref=row.model_profile_ref,
        max_output_tokens=row.max_output_tokens,
        temperature=float(row.temperature),
        created_at=row.created_at,
    )


def _llm_call_row(record: LLMCallAuditEntry) -> LLMCallAuditRow:
    """Convert an LLM audit entry to an ORM row."""
    return LLMCallAuditRow(
        llm_call_id=record.llm_call_id,
        run_id=record.run_id,
        task_id=record.task_id,
        agent_name=record.agent_name,
        provider_name=record.provider_name,
        model_name=record.model_name,
        prompt_render_id=record.prompt_render_id,
        input_token_count=record.input_token_count,
        output_token_count=record.output_token_count,
        temperature=record.temperature,
        status=record.status,
        error_code=record.error_code,
        started_at=record.started_at,
        finished_at=record.finished_at,
    )


def _llm_call_payload(row: LLMCallAuditRow) -> LLMCallAuditEntry:
    """Convert an LLM audit row to an immutable entry."""
    return LLMCallAuditEntry(
        llm_call_id=row.llm_call_id,
        run_id=row.run_id,
        task_id=row.task_id,
        agent_name=row.agent_name,
        provider_name=row.provider_name,
        model_name=row.model_name,
        prompt_render_id=row.prompt_render_id,
        input_token_count=row.input_token_count,
        output_token_count=row.output_token_count,
        temperature=float(row.temperature) if row.temperature is not None else None,
        status=row.status,
        error_code=row.error_code,
        started_at=row.started_at,
        finished_at=row.finished_at,
    )
