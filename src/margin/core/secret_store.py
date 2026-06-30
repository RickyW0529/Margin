"""Encrypted, versioned Secret Store for provider credentials."""

from __future__ import annotations

import base64
import json
import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import BaseModel, Field, SecretStr, field_validator
from sqlalchemy.orm import Session

from margin.news.models import ensure_utc, utc_now
from margin.sql.core_queries import (
    active_secrets_by_provider_and_name,
    secret_by_idempotency,
    secrets_list,
)
from margin.strategy.db_models import ProviderSecretVersionRow


@dataclass(frozen=True)
class SecretVersionRef:
    """Reference to a stored encrypted secret version.

    Attributes:
        version_id: Unique identifier of the secret version.
        provider_name: Name of the provider the secret belongs to.
        secret_name: Name of the secret within the provider.
    """

    version_id: str
    provider_name: str
    secret_name: str


@dataclass(frozen=True)
class SecretMetadata:
    """Write-only secret metadata safe for API responses and logs.

    Attributes:
        ref: Reference to the stored secret version.
        configured: Whether the secret is currently active.
        last_four: Last four characters of the plaintext for display.
        version_id: Unique identifier of the secret version.
        status: Lifecycle status (e.g. ``active``, ``deactivated``).
        updated_at: UTC timestamp of the last status change.
    """

    ref: SecretVersionRef
    configured: bool
    last_four: str
    version_id: str
    status: str
    updated_at: datetime


class SecretValue:
    """Resolved secret value with masked representation.

    Wraps a ``SecretStr`` so that the plaintext is only accessible via
    ``get_secret_value()`` to trusted callers, while ``repr()`` and
    accidental logging show a masked value.
    """

    def __init__(self, value: str) -> None:
        """Initialize with the plaintext value.

        Args:
            value: The plaintext secret value.
        """
        self._secret = SecretStr(value)

    def get_secret_value(self) -> str:
        """Return the plaintext value to trusted provider adapters only.

        Returns:
            The plaintext secret string.
        """
        return self._secret.get_secret_value()

    def __repr__(self) -> str:
        """Return a masked representation safe for logs.

        Returns:
            A masked string that does not expose the secret value.
        """
        return "SecretValue('**********')"


class WriteSecretCommand(BaseModel):
    """Command to create or replace a provider secret.

    Attributes:
        provider_name: Name of the provider the secret belongs to.
        secret_name: Name of the secret within the provider.
        secret_value: Plaintext value to encrypt and store.
        actor_id: Identifier of the user or service writing the secret.
        idempotency_key: Key for deduplicating repeated write requests.
    """

    provider_name: str
    secret_name: str
    secret_value: str
    actor_id: str
    idempotency_key: str

    @field_validator("provider_name", "secret_name", "actor_id", "idempotency_key")
    @classmethod
    def non_empty(cls, value: str) -> str:
        """Normalize and validate non-empty command fields.

        Args:
            value: Raw field value supplied during validation.

        Returns:
            The stripped and normalized field value.

        Raises:
            ValueError: When the value is empty or whitespace-only.
        """
        normalized = value.strip()
        if not normalized:
            raise ValueError("secret command fields must be non-empty")
        return normalized

    @field_validator("secret_value")
    @classmethod
    def secret_non_empty(cls, value: str) -> str:
        """Validate non-empty plaintext before encryption.

        Args:
            value: Raw secret value supplied during validation.

        Returns:
            The original value if non-empty.

        Raises:
            ValueError: When the value is empty.
        """
        if not value:
            raise ValueError("secret_value must be non-empty")
        return value


class SecretRedactor(BaseModel):
    """Redact known secret values from errors before serialization/logging.

    Attributes:
        values: Tuple of known secret plaintext values to redact.
    """

    values: tuple[str, ...] = Field(default_factory=tuple)

    def redact(self, message: str) -> str:
        """Replace every known secret value with ``[REDACTED]``.

        Args:
            message: String that may contain secret values.

        Returns:
            The message with all known secret values replaced by
            ``[REDACTED]``.
        """
        redacted = message
        for value in self.values:
            if value:
                redacted = redacted.replace(value, "[REDACTED]")
        return redacted


class SQLAlchemySecretRepository:
    """Repository for encrypted provider secret versions.

    Persists AES-GCM encrypted secret rows in PostgreSQL via SQLAlchemy,
    supporting idempotent writes, activation, deactivation, and listing
    without decryption.
    """

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        """Initialize the repository.

        Args:
            session_factory: Callable that returns a new SQLAlchemy session.
        """
        self._session_factory = session_factory

    def get(self, version_id: str) -> ProviderSecretVersionRow | None:
        """Fetch one secret row by version id.

        Args:
            version_id: Unique identifier of the secret version.

        Returns:
            The matching ORM row, or None if not found.
        """
        with self._session_factory() as session:
            return session.get(ProviderSecretVersionRow, version_id)

    def find_by_idempotency(
        self,
        *,
        provider_name: str,
        secret_name: str,
        idempotency_key: str,
    ) -> ProviderSecretVersionRow | None:
        """Return a prior write with the same idempotency key if it exists.

        Args:
            provider_name: Name of the provider the secret belongs to.
            secret_name: Name of the secret within the provider.
            idempotency_key: Idempotency key to search for.

        Returns:
            The prior ORM row, or None if no match is found.
        """
        with self._session_factory() as session:
            return session.scalar(
                secret_by_idempotency(provider_name, secret_name, idempotency_key)
            )

    def create_active(
        self,
        row: ProviderSecretVersionRow,
        *,
        provider_name: str,
        secret_name: str,
        deactivated_at: datetime,
    ) -> None:
        """Deactivate existing active rows and persist a new active version.

        Args:
            row: The new secret version row to persist.
            provider_name: Name of the provider the secret belongs to.
            secret_name: Name of the secret within the provider.
            deactivated_at: Timestamp to set on deactivated prior versions.
        """
        with self._session_factory.begin() as session:
            active_rows = session.scalars(
                active_secrets_by_provider_and_name(provider_name, secret_name)
            ).all()
            for active in active_rows:
                active.status = "deactivated"
                active.deactivated_at = deactivated_at
            session.add(row)

    def list(
        self,
        *,
        provider_name: str | None = None,
        secret_name: str | None = None,
    ) -> list[ProviderSecretVersionRow]:
        """List secret rows in creation order without decrypting them.

        Args:
            provider_name: Optional provider name filter.
            secret_name: Optional secret name filter.

        Returns:
            List of matching secret version rows in creation order.
        """
        with self._session_factory() as session:
            return list(
                session.scalars(
                    secrets_list(provider_name, secret_name)
                ).all()
            )

    def deactivate(
        self,
        version_id: str,
        *,
        deactivated_at: datetime,
    ) -> ProviderSecretVersionRow:
        """Deactivate a secret version while preserving decryptable history.

        Args:
            version_id: Unique identifier of the secret version to deactivate.
            deactivated_at: Timestamp to set as the deactivation time.

        Returns:
            The deactivated ORM row.

        Raises:
            KeyError: When no secret version with the given id exists.
        """
        with self._session_factory.begin() as session:
            row = session.get(ProviderSecretVersionRow, version_id)
            if row is None:
                raise KeyError(f"secret version not found: {version_id}")
            if row.status != "deactivated":
                row.status = "deactivated"
                row.deactivated_at = deactivated_at
            return row


class SecretStore:
    """AEAD-encrypted, versioned provider secret store.

    Encrypts plaintext secrets with AES-GCM-256 using a master key and
    persists ciphertext via a SQLAlchemy repository. Supports idempotent
    writes, decryption, metadata retrieval, and deactivation without
    deleting encrypted history.
    """

    def __init__(
        self,
        repository: SQLAlchemySecretRepository,
        *,
        master_key: bytes | str,
        key_version: str = "local-v1",
    ) -> None:
        """Initialize the secret store with an AEAD master key.

        Args:
            repository: Repository for persisting encrypted secret versions.
            master_key: 32-byte key for AES-GCM encryption (raw bytes or base64).
            key_version: Identifier for the key material version.
        """
        self._repository = repository
        self._master_key = _coerce_key(master_key)
        self._key_version = key_version

    def create_or_replace(self, command: WriteSecretCommand) -> SecretMetadata:
        """Encrypt and store a new active secret version.

        If a prior write with the same idempotency key exists, its metadata
        is returned without re-encrypting.

        Args:
            command: Write command containing provider, secret name, value,
                actor, and idempotency key.

        Returns:
            Safe metadata for the stored or prior secret version.
        """
        provider_name = command.provider_name.strip().lower()
        secret_name = command.secret_name.strip().lower()
        prior = self._repository.find_by_idempotency(
            provider_name=provider_name,
            secret_name=secret_name,
            idempotency_key=command.idempotency_key,
        )
        if prior is not None:
            return _metadata_from_row(prior)

        version_id = f"sec_{uuid.uuid4().hex[:12]}"
        nonce = os.urandom(12)
        now = utc_now()
        aad = _associated_data(
            provider_name=provider_name,
            secret_name=secret_name,
            version_id=version_id,
            key_version=self._key_version,
        )
        ciphertext = AESGCM(self._master_key).encrypt(
            nonce,
            command.secret_value.encode("utf-8"),
            aad,
        )
        row = ProviderSecretVersionRow(
            secret_version_id=version_id,
            provider_name=provider_name,
            secret_name=secret_name,
            encrypted_secret=base64.b64encode(ciphertext).decode("ascii"),
            nonce=base64.b64encode(nonce).decode("ascii"),
            key_version=self._key_version,
            algorithm="AESGCM-256",
            last_four=command.secret_value[-4:],
            status="active",
            actor_id=command.actor_id,
            idempotency_key=command.idempotency_key,
            created_at=now,
        )
        self._repository.create_active(
            row,
            provider_name=provider_name,
            secret_name=secret_name,
            deactivated_at=now,
        )
        return _metadata_from_row(row)

    def resolve(self, ref: SecretVersionRef) -> SecretValue:
        """Decrypt a secret version and return a masked value wrapper.

        Args:
            ref: Reference identifying the secret version to decrypt.

        Returns:
            A SecretValue wrapping the decrypted plaintext.

        Raises:
            KeyError: When no secret version with the given id exists.
            ValueError: When AEAD decryption fails (invalid tag or key).
        """
        row = self._repository.get(ref.version_id)
        if row is None:
            raise KeyError(f"secret version not found: {ref.version_id}")
        aad = _associated_data(
            provider_name=row.provider_name,
            secret_name=row.secret_name,
            version_id=row.secret_version_id,
            key_version=row.key_version,
        )
        try:
            plaintext = AESGCM(self._master_key).decrypt(
                base64.b64decode(row.nonce),
                base64.b64decode(row.encrypted_secret),
                aad,
            )
        except (InvalidTag, ValueError) as exc:
            raise ValueError("secret decrypt failed") from exc
        return SecretValue(plaintext.decode("utf-8"))

    def metadata(self, version_id: str) -> SecretMetadata:
        """Return safe metadata for a secret version without decrypting it.

        Args:
            version_id: Unique identifier of the secret version.

        Returns:
            Safe metadata for the secret version.

        Raises:
            KeyError: When no secret version with the given id exists.
        """
        row = self._repository.get(version_id)
        if row is None:
            raise KeyError(f"secret version not found: {version_id}")
        return _metadata_from_row(row)

    def list_metadata(
        self,
        *,
        provider_name: str | None = None,
        secret_name: str | None = None,
    ) -> list[SecretMetadata]:
        """List safe secret metadata without returning encrypted or plain values.

        Args:
            provider_name: Optional provider name filter (case-insensitive).
            secret_name: Optional secret name filter (case-insensitive).

        Returns:
            List of safe metadata objects for matching secret versions.
        """
        normalized_provider = provider_name.strip().lower() if provider_name else None
        normalized_secret = secret_name.strip().lower() if secret_name else None
        return [
            _metadata_from_row(row)
            for row in self._repository.list(
                provider_name=normalized_provider,
                secret_name=normalized_secret,
            )
        ]

    def deactivate(
        self,
        ref: SecretVersionRef,
        *,
        actor_id: str,
        idempotency_key: str,
    ) -> SecretMetadata:
        """Deactivate a secret version without deleting encrypted history.

        Args:
            ref: Reference identifying the secret version to deactivate.
            actor_id: Identifier of the user or service requesting deactivation.
            idempotency_key: Idempotency key for the deactivation request.

        Returns:
            Safe metadata for the deactivated secret version.

        Raises:
            ValueError: When actor_id or idempotency_key is empty.
        """
        if not actor_id.strip() or not idempotency_key.strip():
            raise ValueError("actor_id and idempotency_key are required")
        row = self._repository.deactivate(
            ref.version_id,
            deactivated_at=utc_now(),
        )
        return _metadata_from_row(row)


def _metadata_from_row(row: ProviderSecretVersionRow) -> SecretMetadata:
    """Map a secret version ORM row to a safe metadata object.

    Args:
        row: The secret version ORM row.

    Returns:
        A SecretMetadata instance with no encrypted values exposed.
    """
    return SecretMetadata(
        ref=SecretVersionRef(
            version_id=row.secret_version_id,
            provider_name=row.provider_name,
            secret_name=row.secret_name,
        ),
        configured=row.status == "active",
        last_four=row.last_four,
        version_id=row.secret_version_id,
        status=row.status,
        updated_at=ensure_utc(row.deactivated_at or row.created_at),
    )


def _associated_data(
    *,
    provider_name: str,
    secret_name: str,
    version_id: str,
    key_version: str,
) -> bytes:
    """Build authenticated-associated data bytes for AEAD encryption.

    Args:
        provider_name: Name of the provider the secret belongs to.
        secret_name: Name of the secret.
        version_id: Unique version identifier.
        key_version: Key material version identifier.

    Returns:
        JSON-encoded bytes for use as AEAD associated data.
    """
    payload = {
        "provider_name": provider_name,
        "secret_name": secret_name,
        "version_id": version_id,
        "key_version": key_version,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _coerce_key(master_key: bytes | str) -> bytes:
    """Normalize the master key to exactly 32 raw bytes for AES-GCM-256.

    Args:
        master_key: Key as bytes, base64 string, or raw UTF-8 string.

    Returns:
        32-byte key suitable for AESGCM.

    Raises:
        ValueError: If the resulting key is not 32 bytes.
    """
    if isinstance(master_key, bytes):
        key = master_key
    else:
        try:
            key = base64.b64decode(master_key, validate=True)
        except ValueError:
            key = master_key.encode("utf-8")
    if len(key) != 32:
        raise ValueError("master_key must be 32 bytes for AESGCM-256")
    return key
