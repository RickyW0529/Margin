"""Adversarial nested secret-redaction tests for logs and audit payloads."""

from __future__ import annotations

import structlog

from margin.core.audit import SecretRedactingProcessor
from margin.core.audit_repository import MemoryAuditRepository
from margin.core.logging_config import configure_logging
from margin.core.models import AuditLogRecord


def test_redaction_removes_nested_tokens_and_known_values() -> None:
    """Test that redaction removes nested tokens and known secret values.

    Returns:
        None: .
    """
    processor = SecretRedactingProcessor(secret_values=("secret-token-123",))
    original = {
        "headers": {
            "Authorization": "Bearer secret-token-123",
            "X-Request-Id": "request-1",
        },
        "body": {
            "api_key": "secret-token-123",
            "nested": [{"password": "secret-token-123"}],
        },
        "message": "provider failed with secret-token-123",
    }

    event = processor(None, "info", original)

    assert "secret-token-123" not in str(event)
    assert "[REDACTED]" in str(event)
    assert event["headers"]["X-Request-Id"] == "request-1"
    assert original["body"]["api_key"] == "secret-token-123"


def test_redaction_handles_cookie_traceback_and_exception_values() -> None:
    """Test that redaction handles cookie, traceback, and exception values.

    Returns:
        None: .
    """
    processor = SecretRedactingProcessor(secret_values=("credential-value",))

    event = processor(
        None,
        "error",
        {
            "cookie": "session=credential-value",
            "exception": RuntimeError("credential-value failed"),
            "traceback": [
                "request Authorization=credential-value",
                {"safe": "ok"},
            ],
        },
    )

    rendered = str(event)
    assert "credential-value" not in rendered
    assert event["cookie"] == "[REDACTED]"
    assert "RuntimeError" in event["exception"]
    assert event["traceback"][1]["safe"] == "ok"


def test_audit_repository_redacts_payload_before_persistence() -> None:
    """Test that the audit repository redacts payload before persistence.

    Returns:
        None: .
    """
    repository = MemoryAuditRepository(
        redactor=SecretRedactingProcessor(secret_values=("audit-secret-value",))
    )

    repository.record(
        AuditLogRecord(
            record_id="audit-redaction-1",
            record_type="provider_call",
            payload_json={
                "headers": {"Authorization": "Bearer audit-secret-value"},
                "message": "failed with audit-secret-value",
            },
        )
    )

    rendered = str(repository.list_records()[0].payload_json)
    assert "audit-secret-value" not in rendered
    assert "[REDACTED]" in rendered


def test_configured_logging_redacts_exception_traceback(capsys) -> None:
    """Test that configured logging redacts exception tracebacks.

    Args:
        capsys: Any: .

    Returns:
        None: .
    """
    configure_logging(
        log_level="INFO",
        log_format="json",
        secret_values=("runtime-secret-value",),
    )
    logger = structlog.get_logger("redaction-test")

    try:
        raise RuntimeError("runtime-secret-value failed")
    except RuntimeError:
        logger.exception("provider failed")

    captured = capsys.readouterr().out
    assert "runtime-secret-value" not in captured
    assert "[REDACTED]" in captured
