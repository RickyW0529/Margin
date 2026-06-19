"""SQLAlchemy rows owned by the multi-agent research module."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from margin.storage.base import Base


class ResearchSnapshotRow(Base):
    """Append-only serialized research snapshot."""

    __tablename__ = "research_snapshots"
    __table_args__ = (
        Index("ix_research_snapshots_run_created", "run_id", "created_at"),
    )

    snapshot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    workflow_state: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    input_hash: Mapped[str] = mapped_column(String(96), nullable=False)
    output_hash: Mapped[str] = mapped_column(String(96), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
