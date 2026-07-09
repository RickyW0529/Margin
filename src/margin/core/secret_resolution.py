"""Unified secret resolution preferring the encrypted Secret Store.

Scripts and legacy adapters should call ``resolve_named_secret`` instead of
using ``SecretManager`` (env / plaintext files) directly.
"""

from __future__ import annotations

import os
import warnings
from typing import TYPE_CHECKING

from margin.core.secret import SecretManager, SecretNotFoundError
from margin.core.secret_store import SecretVersionRef

if TYPE_CHECKING:
    from margin.core.secret_store import SecretStore


def resolve_named_secret(
    secret_name: str,
    *,
    provider_name: str | None = None,
    secret_store: SecretStore | None = None,
    allow_legacy_env: bool = True,
) -> str:
    """Resolve a named secret, preferring the encrypted DB-backed Secret Store.

    Resolution order:
    1. Active ``SecretStore`` rows matching ``provider_name`` + ``secret_name``
       (or any provider when ``provider_name`` is None).
    2. Explicit env overrides: ``MARGIN_TUSHARE_TOKEN`` style aliases.
    3. Deprecated ``SecretManager`` (env ``MARGIN_SECRET_*`` / ``.margin/secrets``).

    Args:
        secret_name: Logical secret name (e.g. ``tushare_token``, ``api_key``).
        provider_name: Optional provider filter (e.g. ``tushare``).
        secret_store: Optional pre-built store; when omitted a process container
            store is created when database settings are available.
        allow_legacy_env: When True, fall back to SecretManager with a warning.

    Returns:
        Plaintext secret value.

    Raises:
        SecretNotFoundError: When no source can resolve the secret.
    """
    normalized_secret = secret_name.strip().lower()
    normalized_provider = provider_name.strip().lower() if provider_name else None

    store = secret_store if secret_store is not None else _try_default_secret_store()
    if store is not None:
        value = _resolve_from_store(
            store,
            provider_name=normalized_provider,
            secret_name=normalized_secret,
        )
        if value:
            return value

    # Common CLI env aliases used by operational scripts.
    alias_value = _env_alias(normalized_secret)
    if alias_value:
        return alias_value

    if not allow_legacy_env:
        raise SecretNotFoundError(
            f"Secret '{normalized_secret}' not found in Secret Store"
            + (f" for provider '{normalized_provider}'" if normalized_provider else "")
        )

    warnings.warn(
        "SecretManager env/file fallback is deprecated; configure secrets via "
        "Settings → Provider Secret Store (MARGIN encrypted store).",
        DeprecationWarning,
        stacklevel=2,
    )
    try:
        return SecretManager().resolve(normalized_secret).strip()
    except SecretNotFoundError:
        raise SecretNotFoundError(
            f"Secret '{normalized_secret}' not found in Secret Store or legacy env/files"
        ) from None


def _resolve_from_store(
    store: SecretStore,
    *,
    provider_name: str | None,
    secret_name: str,
) -> str | None:
    """Return the first active matching secret value from the store."""
    candidates = store.list_metadata(
        provider_name=provider_name,
        secret_name=secret_name,
    )
    # Prefer active rows; list is creation-ordered so last active wins.
    active = [item for item in candidates if item.status == "active"]
    chosen = active[-1] if active else (candidates[-1] if candidates else None)
    if chosen is None or not chosen.configured:
        return None
    try:
        return store.resolve(
            SecretVersionRef(
                version_id=chosen.version_id,
                provider_name=chosen.ref.provider_name,
                secret_name=chosen.ref.secret_name,
            )
        ).get_secret_value()
    except (KeyError, ValueError):
        return None


def _try_default_secret_store() -> SecretStore | None:
    """Build the process SecretStore when the database is available."""
    try:
        from margin.bootstrap.container import AppContainer
        from margin.settings import get_settings

        return AppContainer(get_settings()).secret_store
    except Exception:  # noqa: BLE001 - scripts may run without a live database
        return None


def _env_alias(secret_name: str) -> str | None:
    """Resolve well-known direct env aliases without the SecretManager prefix."""
    aliases = {
        "tushare_token": ("MARGIN_TUSHARE_TOKEN",),
        "api_key": ("MARGIN_LLM_API_KEY", "MARGIN_OPENAI_API_KEY"),
    }
    for key in aliases.get(secret_name, ()):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return None
