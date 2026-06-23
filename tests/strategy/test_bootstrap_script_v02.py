"""Bootstrap command configuration tests."""

from __future__ import annotations

from margin.settings import MarginSettings
from scripts.bootstrap_config import build_provider_specs


def test_bootstrap_provider_specs_contain_no_plaintext_secrets() -> None:
    """Non-sensitive bootstrap definitions never copy API keys into config JSON."""
    settings = MarginSettings(
        _env_file=None,
        llm_api_key="llm-secret",
        llm_base_url="https://api.deepseek.com",
        llm_model="deepseek-v4-pro",
        embedding_api_key="embedding-secret",
        embedding_base_url="https://open.bigmodel.cn/api/paas/v4",
        embedding_model="embedding-3",
        websearch_api_key="tavily-secret",
        tushare_token="tushare-secret",
        tushare_http_url="https://teajoin.com",
    )

    specs = build_provider_specs(settings)

    rendered = repr(specs)
    assert {spec.provider_name for spec in specs} >= {
        "akshare",
        "tushare",
        "tavily",
        "llm",
        "embedding",
    }
    tavily = next(spec for spec in specs if spec.provider_name == "tavily")
    assert tavily.base_url == "https://api.tavily.com/search"
    assert "llm-secret" not in rendered
    assert "embedding-secret" not in rendered
    assert "tavily-secret" not in rendered
    assert "tushare-secret" not in rendered
