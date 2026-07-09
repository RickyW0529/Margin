"""Create v1 warehouse and platform schemas.

Revision ID: 20260708_0053_v1_warehouse_schemas
Revises: 20260708_0052_runtime_config
Create Date: 2026-07-08 23:50:00
"""

from __future__ import annotations

# ruff: noqa: E501
from alembic import op

revision = "20260708_0053_v1_schemas"
down_revision = "20260708_0052_runtime_config"
branch_labels = None
depends_on = None

SCHEMAS = (
    "raw_meta",
    "source_tushare",
    "source_akshare",
    "source_filing",
    "source_news",
    "source_web",
    "source_doc",
    "ods",
    "vault",
    "mart_dw",
    "mart",
    "app",
    "agent",
    "tool",
    "prompt",
    "ops",
    "platform",
)

# Contract anchors:
# CREATE SCHEMA IF NOT EXISTS raw_meta
# CREATE SCHEMA IF NOT EXISTS source_tushare
# CREATE SCHEMA IF NOT EXISTS source_akshare
# CREATE SCHEMA IF NOT EXISTS source_filing
# CREATE SCHEMA IF NOT EXISTS source_news
# CREATE SCHEMA IF NOT EXISTS source_web
# CREATE SCHEMA IF NOT EXISTS source_doc
# CREATE SCHEMA IF NOT EXISTS ods
# CREATE SCHEMA IF NOT EXISTS vault
# CREATE SCHEMA IF NOT EXISTS mart_dw
# CREATE SCHEMA IF NOT EXISTS mart
# CREATE SCHEMA IF NOT EXISTS app
# CREATE SCHEMA IF NOT EXISTS agent
# CREATE SCHEMA IF NOT EXISTS tool
# CREATE SCHEMA IF NOT EXISTS prompt
# CREATE SCHEMA IF NOT EXISTS ops
# CREATE SCHEMA IF NOT EXISTS platform


def upgrade() -> None:
    """Create non-destructive v1 schemas."""
    for schema in SCHEMAS:
        op.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")


def downgrade() -> None:
    """Leave schemas in place to avoid dropping legacy/source data."""
    return None
