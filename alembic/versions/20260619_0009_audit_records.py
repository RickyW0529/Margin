"""Create audit_records table.

Revision ID: 20260619_0009_audit
Revises: 20260619_0008_monitoring
Create Date: 2026-06-19 18:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import Column, DateTime, Index, String
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "20260619_0009_audit"
down_revision: str | None = "20260619_0008_monitoring"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_records",
        Column("record_id", String(64), primary_key=True),
        Column("record_type", String(48), nullable=False),
        Column("object_id", String(96), nullable=True),
        Column("trace_id", String(64), nullable=False, default=""),
        Column("input_hash", String(96), nullable=True),
        Column("output_hash", String(96), nullable=True),
        Column("payload_json", JSONB, nullable=True),
        Column("recorded_at", DateTime(timezone=True), nullable=False),
        Column("service_version", String(32), nullable=False, default="0.1.0"),
        Index("ix_audit_records_record_type", "record_type"),
        Index("ix_audit_records_object_id", "object_id"),
        Index("ix_audit_records_trace_id", "trace_id"),
        Index("ix_audit_records_recorded_at", "recorded_at"),
    )


def downgrade() -> None:
    op.drop_table("audit_records")
