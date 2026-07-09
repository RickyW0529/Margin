"""Tests for unified secret resolution."""

from __future__ import annotations

import warnings

from margin.core.secret_resolution import resolve_named_secret
from margin.core.secret_store import (
    SecretStore,
    WriteSecretCommand,
)


class _MemorySecretRepo:
    def __init__(self) -> None:
        self.rows: dict[str, object] = {}
        self.by_idem: dict[tuple[str, str, str], object] = {}

    def find_by_idempotency(self, *, provider_name, secret_name, idempotency_key):
        return self.by_idem.get((provider_name, secret_name, idempotency_key))

    def create_active(self, row, *, provider_name, secret_name, deactivated_at):
        self.rows[row.secret_version_id] = row
        self.by_idem[(provider_name, secret_name, row.idempotency_key)] = row

    def get(self, version_id):
        return self.rows.get(version_id)

    def list(self, *, provider_name=None, secret_name=None):
        items = list(self.rows.values())
        if provider_name:
            items = [row for row in items if row.provider_name == provider_name]
        if secret_name:
            items = [row for row in items if row.secret_name == secret_name]
        return items

    def deactivate(self, version_id, *, deactivated_at):
        return self.rows[version_id]


def test_resolve_named_secret_prefers_secret_store(monkeypatch) -> None:
    """Encrypted store wins over env when both are present."""
    master_key = b"0" * 32
    repo = _MemorySecretRepo()
    store = SecretStore(repo, master_key=master_key)
    store.create_or_replace(
        WriteSecretCommand(
            provider_name="tushare",
            secret_name="tushare_token",
            secret_value="store-token-xyz",
            actor_id="test",
            idempotency_key="idem-1",
        )
    )
    monkeypatch.setenv("MARGIN_TUSHARE_TOKEN", "env-token")
    monkeypatch.setenv("MARGIN_SECRET_TUSHARE_TOKEN", "legacy-token")

    value = resolve_named_secret(
        "tushare_token",
        provider_name="tushare",
        secret_store=store,
    )
    assert value == "store-token-xyz"


def test_resolve_named_secret_falls_back_to_env_alias(monkeypatch) -> None:
    """Direct env aliases still work when the store is empty."""
    monkeypatch.delenv("MARGIN_SECRET_TUSHARE_TOKEN", raising=False)
    monkeypatch.setenv("MARGIN_TUSHARE_TOKEN", "alias-token")
    value = resolve_named_secret(
        "tushare_token",
        secret_store=None,  # force no store
        allow_legacy_env=True,
    )
    # secret_store=None still tries AppContainer; monkeypatch resolution via alias first
    # by injecting empty store path: call with a dummy store that returns nothing.
    class _Empty:
        def list_metadata(self, **_kwargs):
            return []

    value = resolve_named_secret(
        "tushare_token",
        secret_store=_Empty(),  # type: ignore[arg-type]
        allow_legacy_env=True,
    )
    assert value == "alias-token"


def test_secret_manager_resolve_emits_deprecation(monkeypatch) -> None:
    """Legacy SecretManager.resolve warns callers."""
    from margin.core.secret import SecretManager

    monkeypatch.setenv("MARGIN_SECRET_DEMO", "x")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert SecretManager().resolve("demo") == "x"
    assert any(item.category is DeprecationWarning for item in caught)
