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
from sqlalchemy import select
from sqlalchemy.orm import Session

from margin.news.models import ensure_utc, utc_now
from margin.strategy.db_models import ProviderSecretVersionRow


@dataclass(frozen=True)
class SecretVersionRef:
    """Reference to a stored encrypted secret version."""

    version_id: str
    provider_name: str
    secret_name: str


@dataclass(frozen=True)
class SecretMetadata:
    """Write-only secret metadata safe for API responses and logs."""

    ref: SecretVersionRef
    configured: bool
    last_four: str
    version_id: str
    status: str
    updated_at: datetime


class SecretValue:
    """Resolved secret value with masked representation."""

    def __init__(self, value: str) -> None:
        """Initialize with the plaintext value.

        Args:
            value: The plaintext secret value.
        """
        self._secret = SecretStr(value)

    def get_secret_value(self) -> str:
        """Return the plaintext value to trusted provider adapters only."""
        return self._secret.get_secret_value()

    def __repr__(self) -> str:
        """Return a masked representation safe for logs."""
        return "SecretValue('**********')"


class WriteSecretCommand(BaseModel):
    """Command to create or replace a provider secret."""

    provider_name: str
    secret_name: str
    secret_value: str
    actor_id: str
    idempotency_key: str

    @field_validator("provider_name", "secret_name", "actor_id", "idempotency_key")
    @classmethod
    def non_empty(cls, value: str) -> str:
        """Normalize and validate non-empty command fields."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("secret command fields must be non-empty")
        return normalized

    @field_validator("secret_value")
    @classmethod
    def secret_non_empty(cls, value: str) -> str:
        """Validate non-empty plaintext before encryption."""
        if not value:
            raise ValueError("secret_value must be non-empty")
        return value


class SecretRedactor(BaseModel):
    """Redact known secret values from errors before serialization/logging."""

    values: tuple[str, ...] = Field(default_factory=tuple)

    def redact(self, message: str) -> str:
        """Replace every known secret value with ``[REDACTED]``."""
        redacted = message
        for value in self.values:
            if value:
                redacted = redacted.replace(value, "[REDACTED]")
        return redacted


class SQLAlchemySecretRepository:
    """Repository for encrypted provider secret versions."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        """Initialize the repository.

        Args:
            session_factory: Callable that returns a new SQLAlchemy session.
        """
        self._session_factory = session_factory

    def get(self, version_id: str) -> ProviderSecretVersionRow | None:
        """Fetch one secret row by version id."""
        with self._session_factory() as session:
            return session.get(ProviderSecretVersionRow, version_id)

    def find_by_idempotency(
        self,
        *,
        provider_name: str,
        secret_name: str,
        idempotency_key: str,
    ) -> ProviderSecretVersionRow | None:
        """Return a prior write with the same idempotency key if it exists."""
        with self._session_factory() as session:
            return session.scalar(
                select(ProviderSecretVersionRow)
                .where(ProviderSecretVersionRow.provider_name == provider_name)
                .where(ProviderSecretVersionRow.secret_name == secret_name)
                .where(ProviderSecretVersionRow.idempotency_key == idempotency_key)
            )

    def create_active(
        self,
        row: ProviderSecretVersionRow,
        *,
        provider_name: str,
        secret_name: str,
        deactivated_at: datetime,
    ) -> None:
        """Deactivate existing active rows and persist a new active version."""
        with self._session_factory.begin() as session:
            active_rows = session.scalars(
                select(ProviderSecretVersionRow)
                .where(ProviderSecretVersionRow.provider_name == provider_name)
                .where(ProviderSecretVersionRow.secret_name == secret_name)
                .where(ProviderSecretVersionRow.status == "active")
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
        """List secret rows in creation order without decrypting them."""
        with self._session_factory() as session:
            query = select(ProviderSecretVersionRow)
            if provider_name is not None:
                query = query.where(
                    ProviderSecretVersionRow.provider_name == provider_name
                )
            if secret_name is not None:
                query = query.where(
                    ProviderSecretVersionRow.secret_name == secret_name
                )
            return list(
                session.scalars(
                    query.order_by(ProviderSecretVersionRow.created_at)
                ).all()
            )

    def deactivate(
        self,
        version_id: str,
        *,
        deactivated_at: datetime,
    ) -> ProviderSecretVersionRow:
        """Deactivate a secret version while preserving decryptable history."""
        with self._session_factory.begin() as session:
            row = session.get(ProviderSecretVersionRow, version_id)
            if row is None:
                raise KeyError(f"secret version not found: {version_id}")
            if row.status != "deactivated":
                row.status = "deactivated"
                row.deactivated_at = deactivated_at
            return row


class SecretStore:
    """AEAD-encrypted, versioned provider secret store."""

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
        """Encrypt and store a new active secret version."""
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
        """Decrypt a secret version and return a masked value wrapper."""
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
        """Return safe metadata for a secret version without decrypting it."""
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
        """List safe secret metadata without returning encrypted or plain values."""
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
        """Deactivate a secret version without deleting encrypted history."""
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
