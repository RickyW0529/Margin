"""Tests for ``AuditLogger`` and the response-hash utility."""

from datetime import datetime
from pathlib import Path

from margin.core.audit import AuditLogger, AuditRecord, compute_hash
from margin.core.provider import CallResult


class TestComputeHash:
    """Tests covering the format and stability of ``compute_hash``.."""

    def test_dict_hash(self):
        """Test that a dictionary hash is returned with the expected ``sha256:`` prefix.

        Returns:
            Any: .
        """
        h = compute_hash({"a": 1, "b": 2})
        assert h.startswith("sha256:")

    def test_none_hash(self):
        """Test that ``None`` is hashed to the sentinel value ``sha256:none``.

        Returns:
            Any: .
        """
        assert compute_hash(None) == "sha256:none"

    def test_deterministic(self):
        """Test that hashing the same input twice produces the same digest.

        Returns:
            Any: .
        """
        assert compute_hash({"a": 1}) == compute_hash({"a": 1})

    def test_order_independent(self):
        """Test that dictionary key order does not affect the resulting hash.

        Returns:
            Any: .
        """
        assert compute_hash({"a": 1, "b": 2}) == compute_hash({"b": 2, "a": 1})


class TestAuditLogger:
    """Tests covering JSONL persistence, reading, and parameter summarization.."""

    def test_default_log_path_is_project_relative(self, tmp_path, monkeypatch):
        """Test that the default audit log path is relative to the project directory.

        Args:
            tmp_path: Any: .
            monkeypatch: Any: .

        Returns:
            Any: .
        """
        monkeypatch.chdir(tmp_path)
        logger = AuditLogger()
        assert logger._log_path == Path(".margin/audit/provider_calls.jsonl")
        assert not logger._log_path.is_absolute()
        assert (tmp_path / ".margin/audit").is_dir()

    def test_log_call_writes_jsonl(self, tmp_path):
        """Test that ``log_call`` persists a record and returns an ``AuditRecord``.

        Args:
            tmp_path: Any: .

        Returns:
            Any: .
        """
        log_path = tmp_path / "audit.jsonl"
        logger = AuditLogger(log_path=log_path)

        result = CallResult(
            provider_name="akshare",
            provider_version="1.0.0",
            success=True,
            data={"close": 100.0},
            response_hash="sha256:abc",
            fetched_at=datetime(2026, 7, 1, 18, 0, 0),
            cost=0.01,
            latency_ms=50.0,
        )

        record = logger.log_call(
            provider_name="akshare",
            provider_version="1.0.0",
            method="get_bars",
            params={"symbols": ["000001.SZ"], "start": "2026-06-01"},
            result=result,
            trace_id="trace_001",
        )

        assert isinstance(record, AuditRecord)
        assert record.provider_name == "akshare"
        assert record.method == "get_bars"
        assert record.success is True
        assert record.trace_id == "trace_001"
        assert log_path.is_file()

    def test_read_all(self, tmp_path):
        """Test that ``read_all`` returns every persisted record in chronological order.

        Args:
            tmp_path: Any: .

        Returns:
            Any: .
        """
        log_path = tmp_path / "audit.jsonl"
        logger = AuditLogger(log_path=log_path)

        for i in range(3):
            result = CallResult(
                provider_name="p",
                provider_version="1.0",
                success=True,
                fetched_at=datetime(2026, 7, 1),
            )
            logger.log_call("p", "1.0", "method", {"i": i}, result)

        records = logger.read_all()
        assert len(records) == 3
        assert records[0].params_summary == {"i": 0}

    def test_read_all_empty(self, tmp_path):
        """Test that ``read_all`` returns an empty list when the log file does not exist.

        Args:
            tmp_path: Any: .

        Returns:
            Any: .
        """
        logger = AuditLogger(log_path=tmp_path / "nonexist.jsonl")
        assert logger.read_all() == []

    def test_sensitive_params_redacted(self, tmp_path):
        """Test that sensitive parameter keys such as ``token`` are redacted.

        Args:
            tmp_path: Any: .

        Returns:
            Any: .
        """
        logger = AuditLogger(log_path=tmp_path / "audit.jsonl")
        result = CallResult(
            provider_name="tushare",
            provider_version="1.0",
            success=True,
            fetched_at=datetime(2026, 7, 1),
        )
        record = logger.log_call(
            "tushare",
            "1.0",
            "get_bars",
            {"token": "secret123", "symbols": ["000001.SZ"]},
            result,
        )
        assert record.params_summary["token"] == "***REDACTED***"
        assert record.params_summary["symbols"] == ["000001.SZ"]

    def test_long_value_truncated(self, tmp_path):
        """Test that string values longer than 200 characters are truncated.

        Args:
            tmp_path: Any: .

        Returns:
            Any: .
        """
        logger = AuditLogger(log_path=tmp_path / "audit.jsonl")
        result = CallResult(
            provider_name="p",
            provider_version="1",
            success=True,
            fetched_at=datetime(2026, 7, 1),
        )
        long_str = "x" * 300
        record = logger.log_call("p", "1", "m", {"key": long_str}, result)
        assert record.params_summary["key"].endswith("...")
        assert len(record.params_summary["key"]) == 203

    def test_long_list_summarized(self, tmp_path):
        """Test that long list parameters are summarized with their length.

        Args:
            tmp_path: Any: .

        Returns:
            Any: .
        """
        logger = AuditLogger(log_path=tmp_path / "audit.jsonl")
        result = CallResult(
            provider_name="p",
            provider_version="1",
            success=True,
            fetched_at=datetime(2026, 7, 1),
        )
        big_list = list(range(20))
        record = logger.log_call("p", "1", "m", {"ids": big_list}, result)
        assert "len=20" in record.params_summary["ids"]

    def test_record_is_frozen(self, tmp_path):
        """Test that ``AuditRecord`` instances are immutable after creation.

        Args:
            tmp_path: Any: .

        Returns:
            Any: .
        """
        logger = AuditLogger(log_path=tmp_path / "audit.jsonl")
        result = CallResult(
            provider_name="p",
            provider_version="1",
            success=True,
            fetched_at=datetime(2026, 7, 1),
        )
        record = logger.log_call("p", "1", "m", {}, result)
        import pytest

        with pytest.raises(Exception):
            record.success = False
