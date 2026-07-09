"""Frontend API path contract checks against FastAPI OpenAPI."""

from __future__ import annotations

from margin.api.main import create_app

FRONTEND_API_PATHS = {
    "/api/v1/agent-runs/user-qna",
    "/api/v1/agent-schedules/stock-analysis",
    "/api/v1/data-policies",
    "/api/v1/data-policies/{version_id}/activate",
    "/api/v1/data-sync",
    "/api/v1/indicator-views",
    "/api/v1/indicator-views/{version_id}/activate",
    "/api/v1/jobs/{job_run_id}",
    "/api/v1/news/runs/{run_id}",
    "/api/v1/provider-configs",
    "/api/v1/provider-configs/{version_id}/activate",
    "/api/v1/provider-configs/{version_id}/secret",
    "/api/v1/provider-configs/{version_id}/test",
    "/api/v1/provider-status",
    "/api/v1/quant-feature-sets",
    "/api/v1/quant-feature-sets/{version_id}/activate",
    "/api/v1/quant-strategies",
    "/api/v1/quant-strategies/{version_id}/activate",
    "/api/v1/quant-strategy-defaults",
    "/api/v1/research",
    "/api/v1/research-items/{item_id}/feedback",
    "/api/v1/research-scopes",
    "/api/v1/research-scopes/{version_id}/activate",
    "/api/v1/research/items/{item_id}",
    "/api/v1/style-prompts",
    "/api/v1/style-prompts/{version_id}/activate",
    "/api/v1/universe-configs",
    "/api/v1/universe-configs/{version_id}/activate",
    "/api/v1/valuation-discovery/companies/{security_id}/analysis",
    "/api/v1/valuation-discovery/companies/{security_id}/quant",
    "/api/v1/valuation-discovery/refreshes",
    "/api/v1/valuation-discovery/runs",
    "/api/v1/valuation-discovery/runs/{run_id}",
    "/api/v1/strategies",
    "/api/v1/strategies/custom",
    "/api/v1/strategies/templates",
    "/api/v1/strategies/{strategy_id}",
    "/api/v1/strategies/{strategy_id}/archive",
    "/api/v1/strategies/{strategy_id}/versions/{version_id}/activate",
    "/api/v1/strategies/{strategy_id}/versions/{version_id}/backtest",
    "/api/v1/strategies/{strategy_id}/versions/{version_id}/paper-trade",
    "/api/v1/strategies/{strategy_id}/versions/{version_id}/prompt",
    "/api/v1/strategies/{strategy_id}/versions/{version_id}/validate",
}


def test_frontend_api_paths_exist_in_openapi() -> None:
    """Verify frontend client paths are exposed by the backend app.

    Returns:
        None: .
    """
    backend_paths = set(create_app().openapi()["paths"])

    assert FRONTEND_API_PATHS <= backend_paths
