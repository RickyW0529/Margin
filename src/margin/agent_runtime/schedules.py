"""Persisted schedules for agent-driven stock analysis."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from margin.agent_runtime.context_store import make_context_artifact
from margin.agent_runtime.db_models import AgentRuntimeScheduleRow
from margin.agent_runtime.main_agent import MainAgentRuntime
from margin.agent_runtime.models import ContextArtifact
from margin.agent_runtime.quant_agent import current_quant_agent_strategy_profile
from margin.valuation_discovery.service import ValuationDiscoveryService

STOCK_ANALYSIS_SCHEDULE_ID = "stock_analysis_daily"


class StockAnalysisSchedule(BaseModel):
    """User-facing daily scheduled stock-analysis configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schedule_id: str = STOCK_ANALYSIS_SCHEDULE_ID
    run_type: str = "scheduled_stock_analysis"
    enabled: bool = False
    hour: int = Field(default=8, ge=0, le=23)
    minute: int = Field(default=30, ge=0, le=59)
    timezone: str = "Asia/Shanghai"
    scope_version_id: str = "scope-current"
    universe: str = "ALL_A"
    last_triggered_at: datetime | None = None
    next_run_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        """Validate that the timezone name is loadable."""
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown timezone: {value}") from exc
        return value

    def with_next_run(self, *, now: datetime | None = None) -> StockAnalysisSchedule:
        """Return this schedule with its next run timestamp recalculated."""
        resolved_now = now or datetime.now(UTC)
        next_run = (
            compute_next_run_at(
                hour=self.hour,
                minute=self.minute,
                timezone=self.timezone,
                now=resolved_now,
            )
            if self.enabled
            else None
        )
        return self.model_copy(
            update={
                "next_run_at": next_run,
                "updated_at": resolved_now,
            }
        )


class AgentScheduleRepository(Protocol):
    """Repository contract for user-facing agent schedules."""

    def get_stock_analysis_schedule(self) -> StockAnalysisSchedule:
        """Return the stock-analysis schedule, or a disabled default."""

    def save_stock_analysis_schedule(
        self,
        schedule: StockAnalysisSchedule,
    ) -> StockAnalysisSchedule:
        """Persist the stock-analysis schedule."""

    def list_due_stock_analysis_schedules(
        self,
        *,
        now: datetime,
    ) -> list[StockAnalysisSchedule]:
        """Return enabled schedules whose next run is due."""


class MemoryAgentScheduleRepository:
    """In-memory schedule repository for tests."""

    def __init__(self) -> None:
        self._schedule: StockAnalysisSchedule | None = None

    def get_stock_analysis_schedule(self) -> StockAnalysisSchedule:
        return self._schedule or StockAnalysisSchedule()

    def save_stock_analysis_schedule(
        self,
        schedule: StockAnalysisSchedule,
    ) -> StockAnalysisSchedule:
        resolved = schedule.with_next_run(now=schedule.updated_at)
        if self._schedule is not None:
            resolved = resolved.model_copy(update={"created_at": self._schedule.created_at})
        self._schedule = resolved
        return resolved

    def list_due_stock_analysis_schedules(
        self,
        *,
        now: datetime,
    ) -> list[StockAnalysisSchedule]:
        schedule = self.get_stock_analysis_schedule()
        if not schedule.enabled or schedule.next_run_at is None:
            return []
        return [schedule] if schedule.next_run_at <= now else []


class SQLAlchemyAgentScheduleRepository:
    """SQLAlchemy-backed schedule repository."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def get_stock_analysis_schedule(self) -> StockAnalysisSchedule:
        with self._session_factory() as session:
            row = session.get(AgentRuntimeScheduleRow, STOCK_ANALYSIS_SCHEDULE_ID)
            if row is None:
                return StockAnalysisSchedule()
            return StockAnalysisSchedule.model_validate(row.payload)

    def save_stock_analysis_schedule(
        self,
        schedule: StockAnalysisSchedule,
    ) -> StockAnalysisSchedule:
        with self._session_factory.begin() as session:
            current = session.get(AgentRuntimeScheduleRow, schedule.schedule_id)
            created_at = current.created_at if current is not None else schedule.created_at
            resolved = schedule.model_copy(update={"created_at": created_at}).with_next_run(
                now=schedule.updated_at
            )
            payload = resolved.model_dump(mode="json")
            if current is None:
                session.add(
                    AgentRuntimeScheduleRow(
                        schedule_id=resolved.schedule_id,
                        run_type=resolved.run_type,
                        enabled=resolved.enabled,
                        hour=resolved.hour,
                        minute=resolved.minute,
                        timezone=resolved.timezone,
                        scope_version_id=resolved.scope_version_id,
                        universe=resolved.universe,
                        last_triggered_at=resolved.last_triggered_at,
                        next_run_at=resolved.next_run_at,
                        payload=payload,
                        created_at=resolved.created_at,
                        updated_at=resolved.updated_at,
                    )
                )
            else:
                current.run_type = resolved.run_type
                current.enabled = resolved.enabled
                current.hour = resolved.hour
                current.minute = resolved.minute
                current.timezone = resolved.timezone
                current.scope_version_id = resolved.scope_version_id
                current.universe = resolved.universe
                current.last_triggered_at = resolved.last_triggered_at
                current.next_run_at = resolved.next_run_at
                current.payload = payload
                current.updated_at = resolved.updated_at
            return resolved

    def list_due_stock_analysis_schedules(
        self,
        *,
        now: datetime,
    ) -> list[StockAnalysisSchedule]:
        with self._session_factory() as session:
            rows = session.scalars(
                select(AgentRuntimeScheduleRow).where(
                    AgentRuntimeScheduleRow.enabled.is_(True),
                    AgentRuntimeScheduleRow.next_run_at <= now,
                )
            ).all()
            return [StockAnalysisSchedule.model_validate(row.payload) for row in rows]


class ScheduledStockAnalysisRunner:
    """Runs due user-configured stock-analysis schedules."""

    def __init__(
        self,
        *,
        repository: AgentScheduleRepository,
        main_agent: MainAgentRuntime,
        valuation_service: ValuationDiscoveryService,
        scope_resolver: Callable[[str], str],
        write_context_artifact: Callable[[ContextArtifact], None] | None = None,
    ) -> None:
        self._repository = repository
        self._main_agent = main_agent
        self._valuation_service = valuation_service
        self._scope_resolver = scope_resolver
        self._write_context_artifact = (
            write_context_artifact or main_agent.add_context_artifact
        )

    def run_once(self, *, now: datetime | None = None) -> int:
        """Trigger each due enabled schedule once."""
        resolved_now = now or datetime.now(UTC)
        processed = 0
        for schedule in self._repository.list_due_stock_analysis_schedules(
            now=resolved_now,
        ):
            self._trigger(schedule, now=resolved_now)
            processed += 1
        return processed

    def _trigger(self, schedule: StockAnalysisSchedule, *, now: datetime) -> None:
        local_date = now.astimezone(ZoneInfo(schedule.timezone)).date().isoformat()
        run_id = (
            f"ar_sched_{local_date.replace('-', '')}_"
            f"{schedule.hour:02d}{schedule.minute:02d}"
        )
        plan_result = self._main_agent.create_scheduled_stock_analysis_plan(
            run_id=run_id,
            user_intent_summary=(
                f"daily stock analysis for {schedule.universe} at "
                f"{schedule.hour:02d}:{schedule.minute:02d} {schedule.timezone}"
            ),
        )
        quant_profile = current_quant_agent_strategy_profile()
        quant_profile_metadata = quant_profile.to_metadata()
        resolved_scope = self._scope_resolver(schedule.scope_version_id)
        refresh_response = self._valuation_service.start_refresh(
            scope_version_id=resolved_scope,
            decision_at=now,
            idempotency_key=f"{schedule.schedule_id}:{local_date}",
            metadata={
                "agent_run_id": run_id,
                "schedule_id": schedule.schedule_id,
                "universe": schedule.universe,
                "quant_agent_strategy_profile": quant_profile_metadata,
                "quant_strategy": quant_profile.to_quant_strategy_metadata(),
            },
        )
        refresh_run_id = str(getattr(refresh_response, "run_id", ""))
        self._write_context_artifact(
            make_context_artifact(
                artifact_id=f"ctx_{run_id}_valuation_refresh",
                run_id=run_id,
                artifact_type="valuation_refresh",
                producer_agent="QuantAgent",
                payload_json={
                    "schedule_id": schedule.schedule_id,
                    "agent_run_id": run_id,
                    "plan_id": plan_result.plan.plan_id,
                    "planned_steps": [
                        {
                            "step_id": step.step_id,
                            "expert_agent_name": step.expert_agent_name,
                            "skill_id": step.skill_id,
                        }
                        for step in plan_result.plan.steps
                    ],
                    "scope_version_id": resolved_scope,
                    "requested_scope_version_id": schedule.scope_version_id,
                    "universe": schedule.universe,
                    "quant_agent_strategy_profile": quant_profile_metadata,
                    "decision_at": now.isoformat(),
                    "valuation_refresh_run_id": refresh_run_id,
                    "dashboard_projection": "expected_after_refresh",
                },
                source_refs=(
                    plan_result.plan.plan_id,
                    refresh_run_id or "valuation_refresh",
                ),
            )
        )
        self._repository.save_stock_analysis_schedule(
            schedule.model_copy(
                update={
                    "last_triggered_at": now,
                    "updated_at": now,
                }
            )
        )


def compute_next_run_at(
    *,
    hour: int,
    minute: int,
    timezone: str,
    now: datetime,
) -> datetime:
    """Compute the next UTC timestamp for a daily local schedule."""
    local_tz = ZoneInfo(timezone)
    local_now = now.astimezone(local_tz)
    candidate_date: date = local_now.date()
    candidate = datetime.combine(
        candidate_date,
        time(hour=hour, minute=minute),
        tzinfo=local_tz,
    )
    if candidate <= local_now:
        candidate = candidate + timedelta(days=1)
    return candidate.astimezone(UTC)
