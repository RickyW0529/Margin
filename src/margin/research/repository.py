"""Append-only persistence boundaries for research snapshots."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from margin.research.db_models import ResearchSnapshotRow
from margin.research.models import ResearchSnapshot


class ResearchRepository(Protocol):
    """Persistence contract required by :class:`ResearchWorkflow`."""

    def add_snapshot(self, snapshot: ResearchSnapshot) -> None:
        """Persist a snapshot idempotently without allowing mutation."""

    def get_snapshot(self, snapshot_id: str) -> ResearchSnapshot | None:
        """Return a snapshot by identifier."""

    def get_snapshot_for_run(self, run_id: str) -> ResearchSnapshot | None:
        """Return the most recent snapshot for a workflow run."""


class MemoryResearchRepository:
    """Process-local append-only repository used by tests and local callers."""

    def __init__(self) -> None:
        self._snapshots: dict[str, ResearchSnapshot] = {}
        self._run_snapshots: dict[str, str] = {}

    def add_snapshot(self, snapshot: ResearchSnapshot) -> None:
        current = self._snapshots.get(snapshot.snapshot_id)
        if current is not None and current != snapshot:
            raise ValueError(f"research snapshot '{snapshot.snapshot_id}' is immutable")
        self._snapshots[snapshot.snapshot_id] = snapshot
        self._run_snapshots[snapshot.run_id] = snapshot.snapshot_id

    def get_snapshot(self, snapshot_id: str) -> ResearchSnapshot | None:
        return self._snapshots.get(snapshot_id)

    def get_snapshot_for_run(self, run_id: str) -> ResearchSnapshot | None:
        snapshot_id = self._run_snapshots.get(run_id)
        return self.get_snapshot(snapshot_id) if snapshot_id else None


class SQLAlchemyResearchRepository:
    """PostgreSQL-backed append-only research snapshot repository."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def add_snapshot(self, snapshot: ResearchSnapshot) -> None:
        payload = snapshot.model_dump(mode="json")
        with self._session_factory.begin() as session:
            current = session.get(ResearchSnapshotRow, snapshot.snapshot_id)
            if current is None:
                session.add(
                    ResearchSnapshotRow(
                        snapshot_id=snapshot.snapshot_id,
                        run_id=snapshot.run_id,
                        workflow_state=snapshot.workflow_state.value,
                        payload=payload,
                        input_hash=snapshot.input_hash,
                        output_hash=snapshot.output_hash,
                        created_at=snapshot.created_at,
                    )
                )
                return
            if current.payload != payload:
                raise ValueError(
                    f"research snapshot '{snapshot.snapshot_id}' is immutable"
                )

    def get_snapshot(self, snapshot_id: str) -> ResearchSnapshot | None:
        with self._session_factory() as session:
            row = session.get(ResearchSnapshotRow, snapshot_id)
            return ResearchSnapshot.model_validate(row.payload) if row else None

    def get_snapshot_for_run(self, run_id: str) -> ResearchSnapshot | None:
        with self._session_factory() as session:
            row = session.scalars(
                select(ResearchSnapshotRow)
                .where(ResearchSnapshotRow.run_id == run_id)
                .order_by(
                    ResearchSnapshotRow.created_at.desc(),
                    ResearchSnapshotRow.snapshot_id.desc(),
                )
            ).first()
            return ResearchSnapshot.model_validate(row.payload) if row else None
