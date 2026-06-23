"""Tests for immutable audit repository.

Validates append-only semantics, duplicate rejection, and filtering behavior
shared by the memory and SQLAlchemy implementations.
"""

from __future__ import annotations

import pytest

from margin.core.audit_repository import MemoryAuditRepository
from margin.core.models import AuditLogRecord


def test_audit_repository_appends_record():
    """audit repository appends record."""
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


def test_audit_repository_rejects_duplicate_record_id():
    """audit repository rejects duplicate record id."""
    repo = MemoryAuditRepository()
    record = AuditLogRecord(
        record_id="ar_immutable",
        record_type="research_signal",
        object_id="sig_1",
    )
    repo.record(record)

    # Same record_id with a different object_id must still be rejected.
    with pytest.raises(ValueError, match="already exists"):
        repo.record(record.model_copy(update={"object_id": "sig_2"}))

    # Original record remains unchanged.
    assert repo.list_records()[0].object_id == "sig_1"
