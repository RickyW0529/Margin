"""Core infrastructure: Provider Registry, Secret management, audit logging, and resilience.

This module re-exports the public building blocks used by the data layer and
other Margin subsystems.
"""

from margin.core.audit import AuditLogger, AuditRecord, compute_hash
from margin.core.provider import (
    BaseProvider,
    CallResult,
    HealthCheckResult,
    ProviderDescriptor,
    ProviderStatus,
    ProviderType,
)
from margin.core.registry import (
    ProviderAlreadyRegisteredError,
    ProviderNotFoundError,
    ProviderRegistry,
)
from margin.core.resilience import (
    ProviderError,
    RateLimiter,
    RateLimitError,
    RetryConfig,
    with_retry,
)
from margin.core.secret import SecretManager, SecretNotFoundError

__all__ = [
    "AuditLogger",
    "AuditRecord",
    "BaseProvider",
    "CallResult",
    "HealthCheckResult",
    "ProviderAlreadyRegisteredError",
    "ProviderDescriptor",
    "ProviderError",
    "ProviderNotFoundError",
    "ProviderRegistry",
    "ProviderStatus",
    "ProviderType",
    "RateLimitError",
    "RateLimiter",
    "RetryConfig",
    "SecretManager",
    "SecretNotFoundError",
    "compute_hash",
    "with_retry",
]
