#!/usr/bin/env python3
"""Full v0.2 smoke harness with explicit real-provider failure semantics."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from sqlalchemy import create_engine

from margin.core.provider import HealthCheckResult, ProviderStatus
from margin.core.secret_store import SecretRedactor
from margin.data.providers.akshare_provider import AKShareProvider
from margin.data.providers.tushare_provider import TushareProvider
from margin.news.providers.tavily import TavilySearchAdapter
from margin.research.llm import LLMProvider
from margin.sql.health_queries import alembic_version, pgvector_extension
from margin.vector.providers.openai_embedding import OpenAIEmbeddingProvider
from margin.vector.providers.rerank import HTTPRerankProvider

try:
    from scripts.verify_migrations import verify_clean_database
except ModuleNotFoundError:
    from verify_migrations import verify_clean_database


@dataclass(frozen=True)
class SmokeStage:
    """One smoke stage result safe to print or persist."""

    stage: str
    status: str
    latency_ms: int
    external_blocker: str | None = None
    error_code: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


def _secret_values() -> tuple[str, ...]:
    """Collect configured secret env values for redaction."""
    names = (
        "MARGIN_TUSHARE_TOKEN",
        "MARGIN_SECRET_TUSHARE_TOKEN",
        "MARGIN_WEBSEARCH_API_KEY",
        "MARGIN_LLM_API_KEY",
        "MARGIN_EMBEDDING_API_KEY",
        "MARGIN_RERANK_API_KEY",
    )
    return tuple(value for name in names if (value := os.getenv(name)))


def _redact_text(value: str) -> str:
    """Redact known secrets from a text string."""
    return SecretRedactor(values=_secret_values()).redact(value)


def _stage(
    name: str,
    func: Callable[[], dict[str, Any] | None],
) -> SmokeStage:
    """Run a smoke stage function and capture its result."""
    started = time.perf_counter()
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
            io.StringIO()
        ):
            detail = func() or {}
        return SmokeStage(
            stage=name,
            status="passed",
            latency_ms=int((time.perf_counter() - started) * 1000),
            detail=detail,
        )
    except SmokeFailure as exc:
        return SmokeStage(
            stage=name,
            status="failed",
            latency_ms=int((time.perf_counter() - started) * 1000),
            external_blocker=exc.external_blocker,
            error_code=exc.error_code,
            detail=exc.detail,
        )
    except Exception as exc:  # noqa: BLE001
        return SmokeStage(
            stage=name,
            status="failed",
            latency_ms=int((time.perf_counter() - started) * 1000),
            external_blocker=_classify_exception(exc),
            error_code=type(exc).__name__,
            detail={"message": _redact_text(str(exc))[:300]},
        )


def _skipped(name: str, reason: str) -> SmokeStage:
    """Build a skipped smoke stage with a reason."""
    return SmokeStage(
        stage=name,
        status="skipped",
        latency_ms=0,
        external_blocker=reason,
    )


class SmokeFailure(RuntimeError):
    """Expected smoke failure with a stable blocker code."""

    def __init__(
        self,
        *,
        external_blocker: str,
        error_code: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the smoke failure with blocker and error code."""
        super().__init__(error_code)
        self.external_blocker = external_blocker
        self.error_code = error_code
        self.detail = detail or {}


def _require_env(names: tuple[str, ...]) -> dict[str, str]:
    """Require all named env vars or raise SmokeFailure."""
    values: dict[str, str] = {}
    missing: list[str] = []
    for name in names:
        value = os.getenv(name, "").strip()
        if not value:
            missing.append(name)
        else:
            values[name] = value
    if missing:
        raise SmokeFailure(
            external_blocker="missing_secret",
            error_code="missing_configuration",
            detail={"missing": missing},
        )
    return values


def _require_one_env(names: tuple[str, ...]) -> str:
    """Require at least one named env var or raise SmokeFailure."""
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    raise SmokeFailure(
        external_blocker="missing_secret",
        error_code="missing_configuration",
        detail={"missing_any_of": list(names)},
    )


def _classify_exception(exc: Exception) -> str:
    """Classify an exception into a stable blocker code."""
    message = str(exc).lower()
    if (
        "401" in message
        or "403" in message
        or "auth" in message
        or "unauthorized" in message
    ):
        return "auth"
    if "429" in message or "rate limit" in message or "too many" in message:
        return "rate_limit"
    if (
        "timeout" in message
        or "connection" in message
        or "proxy" in message
        or "network" in message
        or isinstance(exc, (TimeoutError, URLError))
    ):
        return "network"
    return "provider"


def _health_to_detail(result: HealthCheckResult) -> dict[str, Any]:
    """Convert a HealthCheckResult to a serializable detail dict."""
    return {
        "provider": result.provider_name,
        "status": result.status.value,
        "latency_ms": result.latency_ms,
        "message": _redact_text(result.message or "")[:300],
    }


def _require_healthy(result: HealthCheckResult) -> dict[str, Any]:
    """Require a healthy provider result or raise SmokeFailure."""
    detail = _health_to_detail(result)
    if result.status != ProviderStatus.HEALTHY:
        raise SmokeFailure(
            external_blocker=_classify_exception(RuntimeError(result.message or "")),
            error_code="provider_unhealthy",
            detail=detail,
        )
    return detail


def _compose_config_stage() -> dict[str, Any]:
    """Validate docker-compose configuration."""
    result = subprocess.run(
        ["docker", "compose", "config", "--quiet"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise SmokeFailure(
            external_blocker="compose",
            error_code="compose_config_failed",
            detail={"stderr": _redact_text(result.stderr)[:300]},
        )
    return {}


def _migration_stage(database_url: str) -> dict[str, Any]:
    """Verify database migration head matches expected."""
    result = verify_clean_database(database_url)
    if result.current_head != result.expected_head:
        raise SmokeFailure(
            external_blocker="migration",
            error_code="migration_head_mismatch",
            detail={
                "current_head": result.current_head,
                "expected_head": result.expected_head,
            },
        )
    return {
        "current_head": result.current_head,
        "table_count": len(result.tables),
        "pgvector_available": result.pgvector_available,
    }


def _database_stage(database_url: str) -> dict[str, Any]:
    """Check database pgvector extension and migration head."""
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            pgvector_available = (
                connection.execute(
                    pgvector_extension()
                ).scalar()
                == 1
            )
            current_head = connection.execute(
                alembic_version()
            ).scalar()
    finally:
        engine.dispose()
    return {
        "current_head": current_head,
        "pgvector_available": pgvector_available,
    }


def _http_health_stage(url: str, *, name: str) -> Callable[[], dict[str, Any]]:
    """Build an HTTP health check stage closure."""
    def check() -> dict[str, Any]:
        """Perform the HTTP health check."""
        try:
            with urlopen(url, timeout=10) as response:
                if response.status >= 400:
                    raise SmokeFailure(
                        external_blocker=name,
                        error_code=f"http_{response.status}",
                    )
                return {"status_code": response.status}
        except SmokeFailure:
            raise
        except Exception as exc:  # noqa: BLE001
            raise SmokeFailure(
                external_blocker=_classify_exception(exc),
                error_code=type(exc).__name__,
            ) from exc

    return check


def _provider_stage(provider: str, *, require_real: bool) -> SmokeStage:
    """Run or skip a provider health-check stage."""
    stage_name = f"provider:{provider}"
    if not require_real:
        return _skipped(stage_name, "real_provider_not_required")
    return _stage(stage_name, lambda: _run_provider(provider))


def _run_provider(provider: str) -> dict[str, Any]:
    """Execute a real provider health check by name."""
    if provider == "tushare":
        token = _require_one_env(("MARGIN_TUSHARE_TOKEN", "MARGIN_SECRET_TUSHARE_TOKEN"))
        return _require_healthy(
            TushareProvider(
                token=token,
                http_url=os.getenv("MARGIN_TUSHARE_HTTP_URL") or None,
            ).healthcheck()
        )
    if provider == "akshare":
        return _require_healthy(AKShareProvider().healthcheck())
    if provider == "tavily":
        values = _require_env(("MARGIN_WEBSEARCH_API_KEY",))
        return _require_healthy(
            TavilySearchAdapter(api_key=values["MARGIN_WEBSEARCH_API_KEY"]).healthcheck()
        )
    if provider == "llm":
        values = _require_env(("MARGIN_LLM_API_KEY", "MARGIN_LLM_BASE_URL"))
        return _require_healthy(
            LLMProvider(
                api_key=values["MARGIN_LLM_API_KEY"],
                base_url=values["MARGIN_LLM_BASE_URL"],
                model=os.getenv("MARGIN_LLM_MODEL") or "deepseek-v4-pro",
            ).healthcheck()
        )
    if provider == "embedding":
        values = _require_env(("MARGIN_EMBEDDING_API_KEY", "MARGIN_EMBEDDING_BASE_URL"))
        return _require_healthy(
            OpenAIEmbeddingProvider(
                api_key=values["MARGIN_EMBEDDING_API_KEY"],
                base_url=values["MARGIN_EMBEDDING_BASE_URL"],
                model=os.getenv("MARGIN_EMBEDDING_MODEL") or "text-embedding-3-small",
                dimension=int(os.getenv("MARGIN_EMBEDDING_DIMENSION") or "1536"),
            ).healthcheck()
        )
    if provider == "rerank":
        values = _require_env(
            ("MARGIN_RERANK_API_KEY", "MARGIN_RERANK_BASE_URL", "MARGIN_RERANK_MODEL")
        )
        return _require_healthy(
            HTTPRerankProvider(
                api_key=values["MARGIN_RERANK_API_KEY"],
                base_url=values["MARGIN_RERANK_BASE_URL"],
                model=values["MARGIN_RERANK_MODEL"],
            ).healthcheck()
        )
    raise SmokeFailure(
        external_blocker="configuration",
        error_code="unknown_provider",
        detail={"provider": provider},
    )


def run_smoke(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    """Run all smoke stages and return an exit code with full payload.

    Args:
        args: Parsed CLI arguments controlling which stages run.

    Returns:
        tuple[int, dict[str, Any]]: Exit code (0 ok, 1 failed) and the full
            smoke payload with per-stage results.
    """
    stages: list[SmokeStage] = []
    if args.skip_compose:
        stages.append(_skipped("compose_config", "skip_compose"))
    else:
        stages.append(_stage("compose_config", _compose_config_stage))

    if args.database_url:
        stages.append(
            _stage("migration_verification", lambda: _migration_stage(args.database_url))
        )
        stages.append(_stage("database_pgvector", lambda: _database_stage(args.database_url)))
    else:
        stages.append(_skipped("migration_verification", "database_url_not_configured"))
        stages.append(_skipped("database_pgvector", "database_url_not_configured"))

    if args.base_url:
        stages.append(
            _stage(
                "api_health",
                _http_health_stage(f"{args.base_url}/health/ready", name="api"),
            )
        )
    else:
        stages.append(_skipped("api_health", "base_url_not_configured"))
    if args.web_url:
        stages.append(_stage("web_health", _http_health_stage(args.web_url, name="web")))
    else:
        stages.append(_skipped("web_health", "web_url_not_configured"))

    providers = [item.strip() for item in args.providers.split(",") if item.strip()]
    for provider in providers:
        stages.append(_provider_stage(provider, require_real=args.require_real_providers))

    # Later v0.2 modules register concrete stage runners. Until then these stages
    # must not pass implicitly.
    for stage_name in (
        "p0_data_to_quant",
        "p1_quant_news_index_evidence_ai",
        "p2_dashboard_secret_ui",
        "crash_recovery_duplicate_trigger_reconciliation",
    ):
        stages.append(_skipped(stage_name, "stage_registered_by_downstream_module"))

    has_failed = any(stage.status == "failed" for stage in stages)
    payload = {
        "status": "failed" if has_failed else "ok",
        "require_real_providers": args.require_real_providers,
        "stages": [asdict(stage) for stage in stages],
    }
    return (1 if has_failed else 0), payload


def _summary_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Build a compact summary payload from the full smoke result."""
    return {
        "status": payload["status"],
        "require_real_providers": payload["require_real_providers"],
        "stages": [
            {
                "stage": stage["stage"],
                "status": stage["status"],
                "external_blocker": stage["external_blocker"],
                "error_code": stage["error_code"],
            }
            for stage in payload["stages"]
        ],
    }


def main(argv: list[str] | None = None) -> int:
    """Run the full v0.2 smoke harness and print a summary.

    Args:
        argv: Optional argument list. When ``None``, arguments are read from
            ``sys.argv``.

    Returns:
        int: 0 when all stages pass, 1 when any stage fails.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url")
    parser.add_argument("--web-url")
    parser.add_argument("--database-url", default=os.getenv("MARGIN_DATABASE_URL", ""))
    parser.add_argument("--require-real-providers", action="store_true")
    parser.add_argument("--skip-compose", action="store_true")
    parser.add_argument(
        "--providers",
        default="akshare,tushare,tavily,llm,embedding,rerank",
    )
    parser.add_argument("--output-json")
    args = parser.parse_args(argv)
    exit_code, payload = run_smoke(args)
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    if args.output_json:
        Path(args.output_json).write_text(rendered + "\n", encoding="utf-8")
    print(json.dumps(_summary_payload(payload), ensure_ascii=False, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
