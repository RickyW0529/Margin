"""Platform runtime persistence boundaries."""

from margin.platform_runtime.repository import (
    DataFreshnessState,
    DeadLetterRecord,
    IdempotencyKeyRecord,
    OutboxEvent,
    SQLAlchemyPlatformRuntimeRepository,
    SystemHealthSnapshot,
)

__all__ = [
    "DataFreshnessState",
    "DeadLetterRecord",
    "IdempotencyKeyRecord",
    "OutboxEvent",
    "SQLAlchemyPlatformRuntimeRepository",
    "SystemHealthSnapshot",
]
