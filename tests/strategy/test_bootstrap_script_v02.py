"""Bootstrap command configuration tests.

This module verifies that the bootstrap configuration builder assembles
provider specs without leaking plaintext secrets into rendered config JSON.
"""

from __future__ import annotations

from margin.settings import MarginSettings
from scripts.bootstrap_config import build_provider_specs


def test_bootstrap_provider_specs_contain_no_plaintext_secrets() -> None:
    """Verify non-sensitive bootstrap definitions never copy API keys into config JSON.

    The rendered provider specs must include all expected providers while
    ensuring that secret values do not appear in any string representation.

    Returns:
        None.
    """
    settings = MarginSettings(_env_file=None)

    specs = build_provider_specs(settings)

    rendered = repr(specs)
    assert {spec.provider_name for spec in specs} >= {
        "akshare",
        "tushare",
        "tavily",
        "llm",
        "embedding",
        "rerank",
    }
    tavily = next(spec for spec in specs if spec.provider_name == "tavily")
    llm = next(spec for spec in specs if spec.provider_name == "llm")
    embedding = next(spec for spec in specs if spec.provider_name == "embedding")
    assert tavily.base_url == "https://api.tavily.com/search"
    assert llm.base_url is None
    assert llm.model_name is None
    assert embedding.non_sensitive_config["dimension"] == 1536
    assert "llm-secret" not in rendered
    assert "embedding-secret" not in rendered
    assert "tavily-secret" not in rendered
    assert "tushare-secret" not in rendered
