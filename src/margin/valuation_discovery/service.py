"""Application service for valuation discovery refreshes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from margin.core.run_states import OrchestrationRun, StepAttempt
from margin.valuation_discovery.orchestrator import (
    ValuationDiscoveryOrchestrator,
    ValuationDiscoveryStepWorker,
)


@dataclass(frozen=True)
class RefreshStartResponse:
    """DTO returned to HTTP/API callers when a refresh is accepted."""

    run_id: str
    status: str = "accepted"
    http_status: int = 202


@dataclass(frozen=True)
class RefreshStatus:
    """DTO describing the current status of a refresh run."""

    run_id: str
    state: str
    scope_version_id: str
    steps: list[dict]


@dataclass(frozen=True)
class RefreshSummary:
    """DTO describing one refresh run row in a list view."""

    run_id: str
    state: str
    scope_version_id: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class ValuationDiscoveryService:
    """Thin application boundary around the valuation discovery orchestrator."""

    def __init__(self, orchestrator: ValuationDiscoveryOrchestrator) -> None:
        """Initialize the service with a valuation discovery orchestrator."""
        self._orchestrator = orchestrator

    def start_refresh(
        self,
        *,
        scope_version_id: str,
        decision_at: datetime,
        idempotency_key: str | None = None,
    ) -> RefreshStartResponse:
        """Start a refresh and return an accepted response DTO."""
        run = self._orchestrator.start(
            scope_version_id=scope_version_id,
            decision_at=decision_at,
            idempotency_key=idempotency_key,
        )
        return _response_from_run(run)

    def get_refresh_status(self, run_id: str) -> RefreshStatus | None:
        """Return the status of a refresh run, or ``None`` if not found."""
        run = self._orchestrator.get_run(run_id)
        if run is None:
            return None
        steps = self._orchestrator.list_steps(run_id)
        return RefreshStatus(
            run_id=run.run_id,
            state=run.state.value,
            scope_version_id=run.scope_version_id or "",
            steps=[_step_to_dict(step) for step in steps.values()],
        )

    def list_refreshes(
        self,
        *,
        scope_version_id: str | None = None,
        state: str | None = None,
        limit: int = 50,
    ) -> list[RefreshSummary]:
        """Return recent refresh runs, newest first."""
        runs = self._orchestrator.list_runs(
            scope_version_id=scope_version_id,
            state=state,
            limit=limit,
        )
        return [
            RefreshSummary(
                run_id=run.run_id,
                state=run.state.value,
                scope_version_id=run.scope_version_id or "",
                created_at=run.created_at,
                started_at=run.started_at,
                finished_at=run.finished_at,
            )
            for run in runs
        ]

    def create_step_worker(self, *, worker_id: str) -> ValuationDiscoveryStepWorker:
        """Create a lease worker sharing this service's durable dependencies."""
        return ValuationDiscoveryStepWorker(
            self._orchestrator.dependencies,
            worker_id=worker_id,
        )


def _step_to_dict(step: StepAttempt) -> dict:
    """Convert a step attempt into a JSON-serializable dictionary."""
    return {
        "step_id": step.step_id,
        "state": step.state.value,
        "attempt_no": step.attempt_no,
        "output_ref": step.output_ref,
        "error_code": step.error_code,
        "started_at": step.started_at.isoformat() if step.started_at else None,
        "finished_at": step.finished_at.isoformat() if step.finished_at else None,
    }


def _response_from_run(run: OrchestrationRun) -> RefreshStartResponse:
    """Convert an orchestration run into a refresh start response DTO."""
    return RefreshStartResponse(run_id=run.run_id)
