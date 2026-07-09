"""Append-only persistence boundaries for research snapshots."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from sqlalchemy.orm import Session

from margin.research.db_models import ResearchSnapshotRow
from margin.research.models import ResearchSnapshot
from margin.sql.research_queries import snapshots_by_run_id


class ResearchRepository(Protocol):
    """Persistence contract required by :class:`ResearchWorkflow`.."""

    def add_snapshot(self, snapshot: ResearchSnapshot) -> None:
        """Persist a snapshot idempotently without allowing mutation.

        Args:
            snapshot: ResearchSnapshot: .

        Returns:
            None: .
        """

    def get_snapshot(self, snapshot_id: str) -> ResearchSnapshot | None:
        """Return a snapshot by identifier.

        Args:
            snapshot_id: str: .

        Returns:
            ResearchSnapshot | None: .
        """

    def get_snapshot_for_run(self, run_id: str) -> ResearchSnapshot | None:
        """Return the most recent snapshot for a workflow run.

        Args:
            run_id: str: .

        Returns:
            ResearchSnapshot | None: .
        """


class MemoryResearchRepository:
    """Process-local append-only repository used by tests and local callers.."""

    def __init__(self) -> None:
        """Initialize empty snapshot stores.

        Returns:
            None: .
        """
        self._snapshots: dict[str, ResearchSnapshot] = {}
        self._run_snapshots: dict[str, str] = {}

    def add_snapshot(self, snapshot: ResearchSnapshot) -> None:
        """Persist a snapshot idempotently in memory.

        Args:
            snapshot: ResearchSnapshot: .

        Returns:
            None: .
        """
        current = self._snapshots.get(snapshot.snapshot_id)
        if current is not None and current != snapshot:
            raise ValueError(f"research snapshot '{snapshot.snapshot_id}' is immutable")
        self._snapshots[snapshot.snapshot_id] = snapshot
        self._run_snapshots[snapshot.run_id] = snapshot.snapshot_id

    def get_snapshot(self, snapshot_id: str) -> ResearchSnapshot | None:
        """Return a snapshot by identifier.

        Args:
            snapshot_id: str: .

        Returns:
            ResearchSnapshot | None: .
        """
        return self._snapshots.get(snapshot_id)

    def get_snapshot_for_run(self, run_id: str) -> ResearchSnapshot | None:
        """Return the most recent snapshot for a workflow run.

        Args:
            run_id: str: .

        Returns:
            ResearchSnapshot | None: .
        """
        snapshot_id = self._run_snapshots.get(run_id)
        return self.get_snapshot(snapshot_id) if snapshot_id else None


class SQLAlchemyResearchRepository:
    """PostgreSQL-backed append-only research snapshot repository.."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        """Initialize the repository.

        Args:
            session_factory: Callable[[], Session]: .

        Returns:
            None: .
        """
        self._session_factory = session_factory

    def add_snapshot(self, snapshot: ResearchSnapshot) -> None:
        """Persist a snapshot idempotently in PostgreSQL.

        Args:
            snapshot: ResearchSnapshot: .

        Returns:
            None: .
        """
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
                raise ValueError(f"research snapshot '{snapshot.snapshot_id}' is immutable")

    def get_snapshot(self, snapshot_id: str) -> ResearchSnapshot | None:
        """Return a snapshot by identifier.

        Args:
            snapshot_id: str: .

        Returns:
            ResearchSnapshot | None: .
        """
        with self._session_factory() as session:
            row = session.get(ResearchSnapshotRow, snapshot_id)
            return ResearchSnapshot.model_validate(row.payload) if row else None

    def get_snapshot_for_run(self, run_id: str) -> ResearchSnapshot | None:
        """Return the most recent snapshot for a workflow run.

        Args:
            run_id: str: .

        Returns:
            ResearchSnapshot | None: .
        """
        with self._session_factory() as session:
            row = session.scalars(snapshots_by_run_id(run_id)).first()
            return ResearchSnapshot.model_validate(row.payload) if row else None
