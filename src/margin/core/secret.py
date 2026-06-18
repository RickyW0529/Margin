"""Secret manager — API keys are referenced locally, never stored in plain text.

Secrets are resolved at runtime from environment variables or a local secrets
directory. Configuration files only store reference names, never the actual
credential values.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel


class SecretNotFoundError(KeyError):
    """Raised when a Secret reference cannot be resolved."""


class SecretManager:
    """Reference-based Secret manager.

    Supports two sources in priority order:
        1. Environment variables (``MARGIN_SECRET_<REF>``).
        2. Local Secret files (``~/.margin/secrets/<ref>`` or a custom directory).

    Each reference name in a ``ProviderDescriptor.secret_refs`` list is resolved
    to the real credential value via ``resolve()``. Only reference names live in
    configuration files; plain text credentials do not.

    Attributes:
        _secrets_dir: Directory used for local Secret files.
        _env_prefix: Prefix for environment variable lookups.
        _cache: In-memory cache of resolved Secret values.
    """

    def __init__(
        self,
        secrets_dir: Path | None = None,
        env_prefix: str = "MARGIN_SECRET_",
    ) -> None:
        """Initialize the Secret manager.

        Args:
            secrets_dir: Directory containing local Secret files. Defaults to
                ``~/.margin/secrets``.
            env_prefix: Prefix for environment variables. Defaults to
                ``MARGIN_SECRET_``.
        """
        self._secrets_dir = secrets_dir or Path.home() / ".margin" / "secrets"
        self._env_prefix = env_prefix
        self._cache: dict[str, str] = {}

    def resolve(self, ref: str) -> str:
        """Resolve a Secret value by its reference name.

        Args:
            ref: Secret reference name (e.g. ``tushare_token``).

        Returns:
            The Secret value as a string.

        Raises:
            SecretNotFoundError: When the reference is not found in either the
                environment variables or the local secrets directory.
        """
        if ref in self._cache:
            return self._cache[ref]

        env_key = f"{self._env_prefix}{ref.upper()}"
        value = os.environ.get(env_key)
        if value is not None:
            self._cache[ref] = value
            return value

        file_path = self._secrets_dir / ref
        if file_path.is_file():
            value = file_path.read_text(encoding="utf-8").strip()
            self._cache[ref] = value
            return value

        raise SecretNotFoundError(
            f"Secret '{ref}' not found: env {env_key} unset and {file_path} missing"
        )

    def has(self, ref: str) -> bool:
        """Check whether a Secret reference can be resolved.

        Args:
            ref: Secret reference name.

        Returns:
            ``True`` if the reference resolves to a value, otherwise ``False``.
        """
        try:
            self.resolve(ref)
            return True
        except SecretNotFoundError:
            return False

    def list_refs(self) -> list[str]:
        """List all resolvable Secret reference names without exposing values.

        Returns:
            Sorted list of reference names found in environment variables and
            local Secret files.
        """
        refs: set[str] = set()

        for key, value in os.environ.items():
            if key.startswith(self._env_prefix) and value:
                ref = key[len(self._env_prefix) :].lower()
                refs.add(ref)

        if self._secrets_dir.is_dir():
            for f in self._secrets_dir.iterdir():
                if f.is_file():
                    refs.add(f.name)

        return sorted(refs)


class SecretRefInfo(BaseModel):
    """Secret reference metadata for display (does not contain the value)."""

    ref: str
    resolvable: bool
