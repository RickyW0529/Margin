"""SQLAlchemy rows owned by the strategy configuration module."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from margin.storage.base import Base


class StrategyProfileRow(Base):
    """Mutable strategy profile header."""

    __tablename__ = "strategy_profiles"

    strategy_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    active_version_id: Mapped[str] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    versions: Mapped[list[StrategyVersionRow]] = relationship(
        "StrategyVersionRow",
        back_populates="profile",
        cascade="all, delete-orphan",
    )


class StrategyVersionRow(Base):
    """Immutable strategy version snapshot."""

    __tablename__ = "strategy_versions"

    version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    strategy_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("strategy_profiles.strategy_id"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(String(4096), nullable=False, default="")
    config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    prompt_layers: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    sandbox_result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    profile: Mapped[StrategyProfileRow] = relationship(
        "StrategyProfileRow",
        back_populates="versions",
    )
