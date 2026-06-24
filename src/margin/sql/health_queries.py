"""Health-check and migration-verification query functions."""

from __future__ import annotations

from sqlalchemy import TextClause

from margin.sql.raw_statements import (
    ACTIVE_PROVIDER_CONFIG_COUNT,
    ALEMBIC_VERSION,
    FAILED_RETRYABLE_COUNT,
    NON_SYSTEM_TABLES,
    OUTBOX_PENDING_COUNT,
    PGVECTOR_EXTENSION,
    RETRYABLE_STEP_COUNT,
    TERMINATE_DATABASE_CONNECTIONS,
    WAITING_BUDGET_COUNT,
    WAITING_RATE_LIMIT_COUNT,
)


def alembic_version() -> TextClause:
    """Return the current Alembic migration version."""
    return ALEMBIC_VERSION


def pgvector_extension() -> TextClause:
    """Check whether the pgvector extension is installed."""
    return PGVECTOR_EXTENSION


def non_system_tables() -> TextClause:
    """List all non-system tables for migration verification."""
    return NON_SYSTEM_TABLES


def terminate_database_connections(database_name: str) -> tuple[TextClause, dict[str, str]]:
    """Terminate active connections to a database before dropping it."""
    return TERMINATE_DATABASE_CONNECTIONS, {"database_name": database_name}


def outbox_pending_count() -> TextClause:
    """Count pending and retryable outbox messages."""
    return OUTBOX_PENDING_COUNT


def active_provider_config_count() -> TextClause:
    """Count active provider configuration versions."""
    return ACTIVE_PROVIDER_CONFIG_COUNT


def retryable_step_count() -> TextClause:
    """Count orchestration steps ready for processing."""
    return RETRYABLE_STEP_COUNT


def queue_counts() -> dict[str, TextClause]:
    """Return all queue-depth probes used by the degraded endpoint."""
    return {
        "waiting_budget": WAITING_BUDGET_COUNT,
        "waiting_rate_limit": WAITING_RATE_LIMIT_COUNT,
        "retry_queue": FAILED_RETRYABLE_COUNT,
        "outbox_pending": OUTBOX_PENDING_COUNT,
    }
