"""Encrypted v0.2 Secret Store tests."""

from __future__ import annotations

import os

import pytest

from margin.core.secret_store import (
    SecretRedactor,
    SecretStore,
    SQLAlchemySecretRepository,
    WriteSecretCommand,
)
from margin.storage.base import Base
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)
from margin.strategy.db_models import ProviderSecretVersionRow


@pytest.fixture
def master_key() -> bytes:
    """Return a random 32-byte master key for encryption tests.

    Returns:
        A freshly generated 32-byte random key.
    """
    return os.urandom(32)


@pytest.fixture
def other_master_key() -> bytes:
    """Return a second random 32-byte master key for decryption failure tests.

    Returns:
        A freshly generated 32-byte random key distinct from ``master_key``.
    """
    return os.urandom(32)


@pytest.fixture
def secret_repository(database_url: str) -> SQLAlchemySecretRepository:
    """Return a clean SQLAlchemy secret repository for the test database.

    Args:
        database_url: The PostgreSQL test database URL fixture.

    Returns:
        A ``SQLAlchemySecretRepository`` with a freshly initialized schema.
    """
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    with session_factory.begin() as session:
        session.query(ProviderSecretVersionRow).delete()
    return SQLAlchemySecretRepository(session_factory)


def test_secret_create_returns_metadata_without_plaintext(
    secret_repository: SQLAlchemySecretRepository,
    master_key: bytes,
) -> None:
    """Test that creating a secret returns metadata without exposing plaintext."""
    store = SecretStore(secret_repository, master_key=master_key)

    metadata = store.create_or_replace(
        WriteSecretCommand(
            provider_name="tushare",
            secret_name="api_token",
            secret_value="abcdef1234567890",
            actor_id="local-admin",
            idempotency_key="idem-1",
        )
    )

    assert metadata.configured is True
    assert metadata.last_four == "7890"
    assert "abcdef" not in repr(metadata)
    assert store.resolve(metadata.ref).get_secret_value() == "abcdef1234567890"


def test_wrong_master_key_cannot_decrypt(
    secret_repository: SQLAlchemySecretRepository,
    master_key: bytes,
    other_master_key: bytes,
) -> None:
    """Test that a wrong master key cannot decrypt a stored secret."""
    store = SecretStore(secret_repository, master_key=master_key)
    metadata = store.create_or_replace(
        WriteSecretCommand(
            provider_name="tavily",
            secret_name="api_key",
            secret_value="tvly-redacted-example",
            actor_id="local-admin",
            idempotency_key="idem-1",
        )
    )

    broken = SecretStore(secret_repository, master_key=other_master_key)

    with pytest.raises(ValueError, match="secret decrypt failed"):
        broken.resolve(metadata.ref)


def test_redactor_removes_secret_from_errors() -> None:
    """Test that the redactor removes secret values from error strings."""
    redactor = SecretRedactor(values=("abcdef1234567890",))

    assert redactor.redact("token=abcdef1234567890") == "token=[REDACTED]"


def test_secret_rotation_lists_safe_metadata_and_deactivates_prior_version(
    secret_repository: SQLAlchemySecretRepository,
    master_key: bytes,
) -> None:
    """Test that secret rotation lists safe metadata and deactivates prior versions."""
    store = SecretStore(secret_repository, master_key=master_key)
    first = store.create_or_replace(
        WriteSecretCommand(
            provider_name="tushare",
            secret_name="api_token",
            secret_value="first-secret-1234",
            actor_id="local-admin",
            idempotency_key="rotate-1",
        )
    )
    second = store.create_or_replace(
        WriteSecretCommand(
            provider_name="tushare",
            secret_name="api_token",
            secret_value="second-secret-5678",
            actor_id="local-admin",
            idempotency_key="rotate-2",
        )
    )

    metadata = store.list_metadata(
        provider_name="tushare",
        secret_name="api_token",
    )

    assert [item.version_id for item in metadata] == [
        first.version_id,
        second.version_id,
    ]
    assert [item.status for item in metadata] == ["deactivated", "active"]
    assert "first-secret" not in repr(metadata)
    assert "second-secret" not in repr(metadata)


def test_secret_can_be_explicitly_deactivated(
    secret_repository: SQLAlchemySecretRepository,
    master_key: bytes,
) -> None:
    """Test that a secret can be explicitly deactivated."""
    store = SecretStore(secret_repository, master_key=master_key)
    metadata = store.create_or_replace(
        WriteSecretCommand(
            provider_name="tavily",
            secret_name="api_key",
            secret_value="secret-to-disable",
            actor_id="local-admin",
            idempotency_key="deactivate-create",
        )
    )

    deactivated = store.deactivate(
        metadata.ref,
        actor_id="local-admin",
        idempotency_key="deactivate-1",
    )

    assert deactivated.configured is False
    assert deactivated.status == "deactivated"
