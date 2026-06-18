"""SecretManager 测试。"""

from pathlib import Path

import pytest

from margin.core.secret import SecretManager, SecretNotFoundError


class TestSecretManager:
    def test_resolve_from_env(self, monkeypatch):
        monkeypatch.setenv("MARGIN_SECRET_TUSHARE_TOKEN", "abc123")
        sm = SecretManager(secrets_dir=Path("/tmp/nonexistent"))
        assert sm.resolve("tushare_token") == "abc123"

    def test_resolve_from_file(self, tmp_path):
        secrets_dir = tmp_path / "secrets"
        secrets_dir.mkdir()
        (secrets_dir / "my_key").write_text("file_secret_value\n", encoding="utf-8")

        sm = SecretManager(secrets_dir=secrets_dir, env_prefix="NONEXISTENT_")
        assert sm.resolve("my_key") == "file_secret_value"

    def test_env_takes_priority_over_file(self, tmp_path, monkeypatch):
        secrets_dir = tmp_path / "secrets"
        secrets_dir.mkdir()
        (secrets_dir / "key1").write_text("from_file", encoding="utf-8")
        monkeypatch.setenv("MARGIN_SECRET_KEY1", "from_env")

        sm = SecretManager(secrets_dir=secrets_dir)
        assert sm.resolve("key1") == "from_env"

    def test_resolve_missing_raises(self, tmp_path, monkeypatch):
        monkeypatch.delenv("MARGIN_SECRET_MISSING", raising=False)
        sm = SecretManager(secrets_dir=tmp_path / "empty", env_prefix="MARGIN_SECRET_")
        with pytest.raises(SecretNotFoundError):
            sm.resolve("missing")

    def test_has_true(self, monkeypatch):
        monkeypatch.setenv("MARGIN_SECRET_EXISTS", "val")
        sm = SecretManager(secrets_dir=Path("/tmp/nonexistent"))
        assert sm.has("exists") is True

    def test_has_false(self, tmp_path, monkeypatch):
        monkeypatch.delenv("MARGIN_SECRET_MISSING", raising=False)
        sm = SecretManager(secrets_dir=tmp_path / "empty")
        assert sm.has("missing") is False

    def test_list_refs(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MARGIN_SECRET_REF_A", "1")
        monkeypatch.setenv("MARGIN_SECRET_REF_B", "2")
        secrets_dir = tmp_path / "secrets"
        secrets_dir.mkdir()
        (secrets_dir / "ref_c").write_text("3", encoding="utf-8")

        sm = SecretManager(secrets_dir=secrets_dir)
        refs = sm.list_refs()
        assert "ref_a" in refs
        assert "ref_b" in refs
        assert "ref_c" in refs

    def test_caches_resolved_value(self, monkeypatch):
        monkeypatch.setenv("MARGIN_SECRET_CACHED", "v1")
        sm = SecretManager(secrets_dir=Path("/tmp/nonexistent"))
        sm.resolve("cached")
        monkeypatch.setenv("MARGIN_SECRET_CACHED", "v2")
        assert sm.resolve("cached") == "v1"
