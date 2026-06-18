"""Create portfolio persistence and pgvector extension.

Revision ID: 20260618_0001
Revises:
Create Date: 2026-06-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260618_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the initial portfolio schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "portfolios",
        sa.Column("portfolio_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("cash", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("portfolio_id"),
    )
    op.create_index("ix_portfolios_user_id", "portfolios", ["user_id"])
    op.create_table(
        "trades",
        sa.Column("trade_id", sa.String(length=64), nullable=False),
        sa.Column("portfolio_id", sa.String(length=64), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("side", sa.String(length=24), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("price", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("amount", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("fee", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("tax", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("traded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("source_ref", sa.String(length=256), nullable=True),
        sa.Column("raw_hash", sa.String(length=96), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["portfolio_id"],
            ["portfolios.portfolio_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("trade_id"),
    )
    op.create_index("ix_trades_portfolio_id", "trades", ["portfolio_id"])
    op.create_index(
        "ix_trades_portfolio_symbol_time",
        "trades",
        ["portfolio_id", "symbol", "traded_at"],
    )
    op.create_table(
        "position_theses",
        sa.Column("thesis_id", sa.String(length=64), nullable=False),
        sa.Column("portfolio_id", sa.String(length=64), nullable=False),
        sa.Column("position_id", sa.String(length=96), nullable=False),
        sa.Column("thesis", sa.Text(), nullable=False),
        sa.Column("entry_conditions", postgresql.JSONB(), nullable=False),
        sa.Column("hold_conditions", postgresql.JSONB(), nullable=False),
        sa.Column("invalidation_conditions", postgresql.JSONB(), nullable=False),
        sa.Column("target_horizon", postgresql.JSONB(), nullable=False),
        sa.Column("next_review_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["portfolio_id"],
            ["portfolios.portfolio_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("thesis_id"),
        sa.UniqueConstraint(
            "portfolio_id",
            "position_id",
            "version",
            name="uq_position_thesis_version",
        ),
    )
    op.create_index(
        "ix_position_theses_portfolio_position",
        "position_theses",
        ["portfolio_id", "position_id", "version"],
    )


def downgrade() -> None:
    """Drop the initial portfolio schema."""
    op.drop_index(
        "ix_position_theses_portfolio_position",
        table_name="position_theses",
    )
    op.drop_table("position_theses")
    op.drop_index("ix_trades_portfolio_symbol_time", table_name="trades")
    op.drop_index("ix_trades_portfolio_id", table_name="trades")
    op.drop_table("trades")
    op.drop_index("ix_portfolios_user_id", table_name="portfolios")
    op.drop_table("portfolios")
