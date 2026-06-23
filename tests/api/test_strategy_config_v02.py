"""v0.2 strategy configuration API security and redaction tests."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from margin.api.main import create_app
from margin.core.secret_store import SecretStore, SQLAlchemySecretRepository
from margin.settings import get_settings
from margin.storage.base import Base
from margin.storage.database import (
    DatabaseSettings,
    create_database_engine,
    create_session_factory,
)
from margin.strategy.db_models import (
    ProviderConfigVersionRow,
    ProviderSecretVersionRow,
    ResearchScopeVersionRow,
    StrategyConfigAuditRow,
)
from margin.strategy.models import (
    ConfigLifecycle,
    ProviderConfigVersion,
    ResearchScopeVersion,
)
from margin.strategy.repository import SQLAlchemyStrategyRepository
from margin.strategy.service import StrategyService


@pytest.fixture
def admin_headers() -> dict[str, str]:
    """admin headers."""
    return {
        "Authorization": "Bearer admin-test-token",
        "X-CSRF-Token": "valid",
    }


@pytest.fixture
def strategy_config_client(
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> TestClient:
    """strategy config client."""
    monkeypatch.setenv("MARGIN_ADMIN_API_TOKEN", "admin-test-token")
    monkeypatch.setenv("MARGIN_CSRF_TOKEN", "valid")
    get_settings.cache_clear()

    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    with session_factory.begin() as session:
        session.query(StrategyConfigAuditRow).delete()
        session.query(ResearchScopeVersionRow).delete()
        session.query(ProviderConfigVersionRow).delete()
        session.query(ProviderSecretVersionRow).delete()
    secret_store = SecretStore(
        SQLAlchemySecretRepository(session_factory),
        master_key=os.urandom(32),
    )

    repository = SQLAlchemyStrategyRepository(session_factory)
    repository.save_provider_config(
        ProviderConfigVersion(
            version_id="provider-tushare-1",
            provider_name="tushare",
            provider_type="market_data",
            lifecycle=ConfigLifecycle.DRAFT,
        )
    )
    repository.save_research_scope(
        ResearchScopeVersion(
            version_id="scope-1",
            universe_version_id="univ-1",
            indicator_view_version_id="view-1",
            quant_feature_set_version_id="feature-1",
            quant_strategy_version_id="qstrat-1",
            ai_prompt_version_id="prompt-1",
            canonical_rule_version="canonical-v0.2.0",
            tool_policy_version_id="tool-policy-1",
            lifecycle=ConfigLifecycle.REVIEW,
        )
    )
    app = create_app(
        strategy_service=StrategyService(repository=repository),
        strategy_repository=repository,
        secret_store=secret_store,
    )
    return TestClient(app)


def test_write_secret_returns_only_metadata(
    strategy_config_client: TestClient,
    admin_headers: dict[str, str],
) -> None:
    """write secret returns only metadata."""
    response = strategy_config_client.put(
        "/api/v1/provider-configs/provider-tushare-1/secret",
        json={"secret_name": "api_token", "secret_value": "abcdef1234567890"},
        headers={
            **admin_headers,
            "Idempotency-Key": "idem-secret-1",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is True
    assert body["last_four"] == "7890"
    assert "secret_value" not in body
    assert "encrypted_secret" not in body
    assert "nonce" not in body


def test_list_provider_configs_returns_safe_secret_metadata(
    strategy_config_client: TestClient,
    admin_headers: dict[str, str],
) -> None:
    """list provider configs returns safe secret metadata."""
    written = strategy_config_client.put(
        "/api/v1/provider-configs/provider-tushare-1/secret",
        json={"secret_name": "api_token", "secret_value": "abcdef1234567890"},
        headers={
            **admin_headers,
            "Idempotency-Key": "idem-secret-list",
        },
    )
    assert written.status_code == 200

    response = strategy_config_client.get("/api/v1/provider-configs")

    assert response.status_code == 200
    body = response.json()[0]
    assert body["secret_metadata"]["last_four"] == "7890"
    assert "secret_version_id" not in body
    assert "encrypted_secret" not in str(body)
    assert "abcdef1234567890" not in str(body)


def test_list_provider_configs_works_without_secret_master_key(
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Read-only config discovery must not require decrypt authority."""
    monkeypatch.delenv("MARGIN_SECRET_MASTER_KEY", raising=False)
    get_settings.cache_clear()
    engine = create_database_engine(DatabaseSettings(url=database_url))
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    with session_factory.begin() as session:
        session.query(ProviderConfigVersionRow).delete()
    repository = SQLAlchemyStrategyRepository(session_factory)
    repository.save_provider_config(
        ProviderConfigVersion(
            version_id="provider-llm-no-secret",
            provider_name="llm",
            provider_type="llm",
            base_url="https://api.deepseek.com",
            model_name="deepseek-v4-pro",
            lifecycle=ConfigLifecycle.DRAFT,
        )
    )
    app = create_app(
        strategy_service=StrategyService(repository=repository),
        strategy_repository=repository,
    )

    response = TestClient(app, raise_server_exceptions=False).get(
        "/api/v1/provider-configs"
    )

    assert response.status_code == 200
    assert response.json() == [
        {
            "version_id": "provider-llm-no-secret",
            "provider_name": "llm",
            "provider_type": "llm",
            "enabled": True,
            "lifecycle": "draft",
            "base_url": "https://api.deepseek.com",
            "model_name": "deepseek-v4-pro",
            "secret_metadata": None,
        }
    ]
    engine.dispose()


def test_duplicate_secret_write_is_idempotent_and_audited_once(
    strategy_config_client: TestClient,
    admin_headers: dict[str, str],
    database_url: str,
) -> None:
    """duplicate secret write is idempotent and audited once."""
    headers = {
        **admin_headers,
        "Idempotency-Key": "idem-secret-replay",
    }
    first = strategy_config_client.put(
        "/api/v1/provider-configs/provider-tushare-1/secret",
        json={"secret_name": "api_token", "secret_value": "abcdef1234567890"},
        headers=headers,
    )
    replay = strategy_config_client.put(
        "/api/v1/provider-configs/provider-tushare-1/secret",
        json={"secret_name": "api_token", "secret_value": "abcdef1234567890"},
        headers=headers,
    )

    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json()["version_id"] == first.json()["version_id"]

    engine = create_database_engine(DatabaseSettings(url=database_url))
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        secret_count = (
            session.query(ProviderSecretVersionRow)
            .filter_by(idempotency_key="idem-secret-replay")
            .count()
        )
        audit_count = (
            session.query(StrategyConfigAuditRow)
            .filter_by(
                actor_id="local-admin",
                action="provider_secret.write",
                idempotency_key="idem-secret-replay",
            )
            .count()
        )
        audit_details = (
            session.query(StrategyConfigAuditRow)
            .filter_by(
                actor_id="local-admin",
                action="provider_secret.write",
                idempotency_key="idem-secret-replay",
            )
            .one()
            .details
        )
    engine.dispose()

    assert secret_count == 1
    assert audit_count == 1
    assert "abcdef1234567890" not in str(audit_details)
    assert "encrypted_secret" not in audit_details
    assert "nonce" not in audit_details


def test_duplicate_provider_config_create_replays_prior_result(
    strategy_config_client: TestClient,
    admin_headers: dict[str, str],
    database_url: str,
) -> None:
    """duplicate provider config create replays prior result."""
    headers = {
        **admin_headers,
        "Idempotency-Key": "idem-provider-create",
    }
    payload = {
        "version_id": "provider-tavily-1",
        "provider_name": "tavily",
        "provider_type": "websearch",
        "base_url": "https://api.tavily.com/search",
        "lifecycle": "draft",
    }

    first = strategy_config_client.post(
        "/api/v1/provider-configs",
        json=payload,
        headers=headers,
    )
    replay = strategy_config_client.post(
        "/api/v1/provider-configs",
        json=payload,
        headers=headers,
    )

    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json()["version_id"] == first.json()["version_id"]

    engine = create_database_engine(DatabaseSettings(url=database_url))
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        audit_count = (
            session.query(StrategyConfigAuditRow)
            .filter_by(
                action="provider_config.create",
                idempotency_key="idem-provider-create",
            )
            .count()
        )
    engine.dispose()

    assert audit_count == 1


def test_write_secret_requires_admin_and_csrf(
    strategy_config_client: TestClient,
) -> None:
    """write secret requires admin and csrf."""
    response = strategy_config_client.put(
        "/api/v1/provider-configs/provider-tushare-1/secret",
        json={"secret_name": "api_token", "secret_value": "abcdef"},
        headers={"Idempotency-Key": "idem-secret-1"},
    )

    assert response.status_code in {401, 403}


def test_activate_scope_rejects_missing_idempotency_key(
    strategy_config_client: TestClient,
    admin_headers: dict[str, str],
) -> None:
    """activate scope rejects missing idempotency key."""
    response = strategy_config_client.post(
        "/api/v1/research-scopes/scope-1/activate",
        headers=admin_headers,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Idempotency-Key header is required"
