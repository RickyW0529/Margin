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
from margin.strategy.repository import MemoryStrategyRepository, SQLAlchemyStrategyRepository
from margin.strategy.service import StrategyService


@pytest.fixture
def admin_headers() -> dict[str, str]:
    """Return no auth headers for personal-mode API calls.

    Returns:
        dict[str, str]: .
    """
    return {}


@pytest.fixture
def strategy_config_client(
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> TestClient:
    """Return an authenticated strategy config API client with seeded data.

    Args:
        database_url: str: .
        monkeypatch: pytest.MonkeyPatch: .

    Returns:
        TestClient: .
    """
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
    """Test that writing a secret returns only safe metadata, never plaintext.

    Args:
        strategy_config_client: TestClient: .
        admin_headers: dict[str, str]: .

    Returns:
        None: .
    """
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
    """Test that listing provider configs returns safe secret metadata.

    Args:
        strategy_config_client: TestClient: .
        admin_headers: dict[str, str]: .

    Returns:
        None: .
    """
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


def test_writing_secret_for_new_provider_config_does_not_deactivate_existing_config_secret(
    strategy_config_client: TestClient,
    admin_headers: dict[str, str],
) -> None:
    """Secret rotation should be scoped to a provider config version.

    Args:
        strategy_config_client: TestClient: .
        admin_headers: dict[str, str]: .

    Returns:
        None: .
    """
    first = strategy_config_client.put(
        "/api/v1/provider-configs/provider-tushare-1/secret",
        json={"secret_name": "api_token", "secret_value": "first-token-1234"},
        headers={
            **admin_headers,
            "Idempotency-Key": "idem-secret-first-config",
        },
    )
    assert first.status_code == 200

    created = strategy_config_client.post(
        "/api/v1/provider-configs",
        json={
            "version_id": "provider-tushare-2",
            "owner_id": "local-admin",
            "provider_name": "tushare",
            "provider_type": "market_data",
            "base_url": "https://api.tushare.pro",
            "model_name": None,
            "non_sensitive_config": {"provider_category": "data_source"},
            "enabled": True,
            "lifecycle": "draft",
        },
        headers={
            **admin_headers,
            "Idempotency-Key": "idem-provider-create-tushare-2",
        },
    )
    assert created.status_code == 200

    second = strategy_config_client.put(
        "/api/v1/provider-configs/provider-tushare-2/secret",
        json={"secret_name": "api_token", "secret_value": "second-token-5678"},
        headers={
            **admin_headers,
            "Idempotency-Key": "idem-secret-second-config",
        },
    )
    assert second.status_code == 200

    response = strategy_config_client.get("/api/v1/provider-configs")

    assert response.status_code == 200
    by_id = {item["version_id"]: item for item in response.json()}
    assert by_id["provider-tushare-1"]["secret_metadata"]["configured"] is True
    assert by_id["provider-tushare-1"]["secret_metadata"]["last_four"] == "1234"
    assert by_id["provider-tushare-2"]["secret_metadata"]["configured"] is True
    assert by_id["provider-tushare-2"]["secret_metadata"]["last_four"] == "5678"


def test_write_secret_to_active_provider_config_does_not_create_orphan_secret(
    strategy_config_client: TestClient,
    admin_headers: dict[str, str],
    database_url: str,
) -> None:
    """Rejected active-config writes must not mutate encrypted secrets.

    Args:
        strategy_config_client: TestClient: .
        admin_headers: dict[str, str]: .
        database_url: str: .

    Returns:
        None: .
    """
    written = strategy_config_client.put(
        "/api/v1/provider-configs/provider-tushare-1/secret",
        json={"secret_name": "api_token", "secret_value": "first-token-1234"},
        headers={
            **admin_headers,
            "Idempotency-Key": "idem-secret-before-active",
        },
    )
    assert written.status_code == 200
    original_secret_id = written.json()["version_id"]

    engine = create_database_engine(DatabaseSettings(url=database_url))
    session_factory = create_session_factory(engine)
    with session_factory.begin() as session:
        provider = session.get(ProviderConfigVersionRow, "provider-tushare-1")
        assert provider is not None
        provider.lifecycle = ConfigLifecycle.ACTIVE.value

    rejected = strategy_config_client.put(
        "/api/v1/provider-configs/provider-tushare-1/secret",
        json={"secret_name": "api_token", "secret_value": "second-token-5678"},
        headers={
            **admin_headers,
            "Idempotency-Key": "idem-secret-rejected-active",
        },
    )

    assert rejected.status_code == 400
    with session_factory() as session:
        secrets = session.query(ProviderSecretVersionRow).filter_by(secret_name="api_token").all()
        original = session.get(ProviderSecretVersionRow, original_secret_id)
    engine.dispose()

    assert len(secrets) == 1
    assert original is not None
    assert original.status == "active"


def test_list_provider_configs_returns_category_and_detected_label(
    strategy_config_client: TestClient,
) -> None:
    """Provider list responses should include safe router metadata for UI tags.

    Args:
        strategy_config_client: TestClient: .

    Returns:
        None: .
    """
    response = strategy_config_client.get("/api/v1/provider-configs")

    assert response.status_code == 200
    body = response.json()[0]
    assert body["provider_category"] == "data_source"
    assert body["detected_provider"] == "tushare"
    assert body["detected_label"] == "Tushare"
    assert body["is_custom_provider"] is False


def test_create_provider_config_enriches_router_metadata(
    strategy_config_client: TestClient,
    admin_headers: dict[str, str],
) -> None:
    """Creating from a category URL should persist backend-derived detection metadata.

    Args:
        strategy_config_client: TestClient: .
        admin_headers: dict[str, str]: .

    Returns:
        None: .
    """
    response = strategy_config_client.post(
        "/api/v1/provider-configs",
        json={
            "version_id": "provider-llm-deepseek",
            "provider_name": "llm",
            "provider_type": "llm",
            "base_url": "https://api.deepseek.com/v1",
            "model_name": "deepseek-chat",
            "non_sensitive_config": {},
            "lifecycle": "draft",
        },
        headers={
            **admin_headers,
            "Idempotency-Key": "idem-provider-create-deepseek",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["non_sensitive_config"]["provider_category"] == "llm"
    assert body["non_sensitive_config"]["detected_provider"] == "deepseek"
    assert body["non_sensitive_config"]["router_rule_id"] == "llm.deepseek"


def test_list_provider_configs_works_with_local_default_secret_key(
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that read-only config discovery works with the local default key.

    Args:
        database_url: str: .
        monkeypatch: pytest.MonkeyPatch: .

    Returns:
        None: .
    """
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

    response = TestClient(app, raise_server_exceptions=False).get("/api/v1/provider-configs")

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
            "provider_category": "llm",
            "detected_provider": "deepseek",
            "detected_label": "DeepSeek",
            "is_custom_provider": False,
            "secret_metadata": None,
        }
    ]
    engine.dispose()


def test_quant_strategy_defaults_expose_three_pool_manual_presets() -> None:
    """Test that quant strategy defaults expose the three user-selectable pools.

    Returns:
        None: .
    """
    app = create_app(strategy_service=StrategyService(repository=MemoryStrategyRepository()))

    response = TestClient(app).get("/api/v1/quant-strategy-defaults")

    assert response.status_code == 200
    body = response.json()
    assert set(body["presets"]) == {"CSI300", "ALL_A", "CSI500"}
    assert body["default_universe"] == "ALL_A"
    assert body["presets"]["ALL_A"]["candidate_policy"]["no_top_n"] is True
    assert body["presets"]["ALL_A"]["candidate_policy"]["market_cap_filter"] is False
    assert body["presets"]["ALL_A"]["factor_weights"]["theme_hotness"] == pytest.approx(0.10)
    assert body["presets"]["ALL_A"]["candidate_policy"]["theme_tilt"]["entry_score"] == 70.0
    assert (
        body["presets"]["ALL_A"]["candidate_policy"]["manual_rebalance"]["min_holding_months"] == 2
    )
    assert body["presets"]["CSI300"]["rebalance_frequency"] == "monthly"


def test_duplicate_secret_write_is_idempotent_and_audited_once(
    strategy_config_client: TestClient,
    admin_headers: dict[str, str],
    database_url: str,
) -> None:
    """Test that duplicate secret writes are idempotent and audited exactly once.

    Args:
        strategy_config_client: TestClient: .
        admin_headers: dict[str, str]: .
        database_url: str: .

    Returns:
        None: .
    """
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
    """Test that duplicate provider config creation replays the prior result.

    Args:
        strategy_config_client: TestClient: .
        admin_headers: dict[str, str]: .
        database_url: str: .

    Returns:
        None: .
    """
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


def test_write_secret_accepts_personal_mode_without_admin_and_csrf(
    strategy_config_client: TestClient,
) -> None:
    """Test that personal-mode secret writes do not require admin/CSRF headers.

    Args:
        strategy_config_client: TestClient: .

    Returns:
        None: .
    """
    response = strategy_config_client.put(
        "/api/v1/provider-configs/provider-tushare-1/secret",
        json={"secret_name": "api_token", "secret_value": "abcdef"},
        headers={"Idempotency-Key": "idem-secret-1"},
    )

    assert response.status_code == 200
    assert response.json()["configured"] is True


def test_activate_scope_rejects_missing_idempotency_key(
    strategy_config_client: TestClient,
    admin_headers: dict[str, str],
) -> None:
    """Test that activating a scope rejects requests missing the idempotency key.

    Args:
        strategy_config_client: TestClient: .
        admin_headers: dict[str, str]: .

    Returns:
        None: .
    """
    response = strategy_config_client.post(
        "/api/v1/research-scopes/scope-1/activate",
        headers=admin_headers,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Idempotency-Key header is required"
