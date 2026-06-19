"""Tests for immutable audit repository."""

from __future__ import annotations

from margin.core.audit_repository import MemoryAuditRepository
from margin.core.models import AuditLogRecord


def test_audit_repository_appends_record():
    repo = MemoryAuditRepository()
    record = AuditLogRecord(
        record_type="research_signal",
        object_id="sig_1",
        trace_id="t1",
        input_hash="sha256:abc",
        output_hash="sha256:def",
    )
    repo.record(record)
    assert len(repo.list_records("research_signal")) == 1
