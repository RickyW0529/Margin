"""Firecrawl WebSearch / scrape adapter.

Thin HTTP client around Firecrawl search and scrape APIs. Runtime configuration
is supplied by the provider runtime layer after encrypted secrets are resolved.
Search results map into the same raw dict contract as Tavily so NewsRefresh and
WebSearchProvider can swap backends without pipeline changes.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any
from urllib.parse import urlparse

from margin.core.provider import (
    HealthCheckResult,
    ProviderDescriptor,
    ProviderStatus,
    ProviderType,
)
from margin.core.ssrf import SSRFError, assert_public_http_url
from margin.news.models import utc_now

DEFAULT_FIRECRAWL_BASE_URL = "https://api.firecrawl.dev"
_DEFAULT_SEARCH_SOURCES = ("web", "news")


class FirecrawlErrorCode(StrEnum):
    """Stable token-safe Firecrawl error codes."""

    RATE_LIMITED = "provider_429"
    AUTH_FAILED = "provider_auth_failed"
    SERVER_ERROR = "provider_5xx"
    TIMEOUT = "provider_timeout"
    BAD_RESPONSE = "provider_bad_response"
    SSRF_BLOCKED = "provider_ssrf_blocked"
    BAD_REQUEST = "provider_bad_request"


class FirecrawlProviderError(RuntimeError):
    """Token-safe Firecrawl provider error."""

    def __init__(
        self,
        *,
        code: FirecrawlErrorCode,
        retryable: bool,
        message: str,
        retry_after_seconds: int | None = None,
    ) -> None:
        """Initialize the error."""
        self.provider_name = "firecrawl_websearch"
        self.code = code
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds
        super().__init__(message)


class FirecrawlSearchAdapter:
    """Adapter mapping Firecrawl HTTP responses into Margin search/scrape results."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        client: Any | None = None,
        base_url: str = DEFAULT_FIRECRAWL_BASE_URL,
        timeout: float = 30.0,
        allow_local_urls: bool = False,
        resolve_dns: bool = True,
    ) -> None:
        """Initialize the Firecrawl adapter."""
        self._api_key = api_key
        if not self._api_key:
            raise RuntimeError("Firecrawl API key is required")
        if client is None:
            import httpx

            client = httpx.Client()
        self._client = client
        self._api_root = _normalize_api_root(base_url)
        self._timeout = timeout
        self._allow_local_urls = allow_local_urls
        self._resolve_dns = resolve_dns
        self._descriptor = ProviderDescriptor(
            name="firecrawl_websearch",
            version="firecrawl_search_v2",
            provider_type=ProviderType.WEB_SEARCH,
            capabilities=["search", "scrape"],
            secret_refs=["websearch_api_key"],
            config={"base_url": self._api_root},
        )

    @property
    def descriptor(self) -> ProviderDescriptor:
        """Return the provider descriptor."""
        return self._descriptor

    def search(
        self,
        query: str,
        max_results: int = 10,
        *,
        sources: list[str] | tuple[str, ...] | None = None,
    ) -> list[dict[str, str]]:
        """Execute a Firecrawl search and return raw result dictionaries."""
        normalized_query = str(query or "").strip()
        if not normalized_query:
            raise FirecrawlProviderError(
                code=FirecrawlErrorCode.BAD_REQUEST,
                retryable=False,
                message="Firecrawl search query is required",
            )
        if len(normalized_query) > 500:
            raise FirecrawlProviderError(
                code=FirecrawlErrorCode.BAD_REQUEST,
                retryable=False,
                message="Firecrawl search query exceeds 500 characters",
            )
        limit = max(1, min(int(max_results), 100))
        payload: dict[str, Any] = {
            "query": normalized_query,
            "limit": limit,
        }
        source_payload = _normalize_sources(sources)
        if source_payload:
            payload["sources"] = source_payload

        response = self._client.post(
            f"{self._api_root}/v2/search",
            headers=self._headers(),
            json=payload,
            timeout=self._timeout,
        )
        self._raise_for_status(response, action="search")
        body = _response_json(response)
        _raise_for_unsuccessful_envelope(body, action="search")
        items = _extract_search_items(body)
        results: list[dict[str, str]] = []
        for item in items:
            if not isinstance(item, dict):
                raise FirecrawlProviderError(
                    code=FirecrawlErrorCode.BAD_RESPONSE,
                    retryable=False,
                    message="Malformed Firecrawl response: result must be object",
                )
            url = str(item.get("url") or item.get("imageUrl") or "").strip()
            title = str(item.get("title") or "").strip()
            snippet = str(
                item.get("description")
                or item.get("snippet")
                or item.get("content")
                or ""
            ).strip()
            if not url and not title and not snippet:
                continue
            results.append({"url": url, "title": title, "snippet": snippet})
            if len(results) >= limit:
                break
        return results

    def scrape(
        self,
        url: str,
        *,
        only_main_content: bool = True,
        max_chars: int = 12_000,
        formats: list[str] | tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        """Scrape one public URL into truncated markdown for agents."""
        target = str(url or "").strip()
        if not target:
            raise FirecrawlProviderError(
                code=FirecrawlErrorCode.BAD_REQUEST,
                retryable=False,
                message="Firecrawl scrape url is required",
            )
        try:
            assert_public_http_url(
                target,
                allow_local=self._allow_local_urls,
                resolve_dns=self._resolve_dns,
            )
        except SSRFError as exc:
            raise FirecrawlProviderError(
                code=FirecrawlErrorCode.SSRF_BLOCKED,
                retryable=False,
                message=f"Firecrawl scrape blocked by SSRF policy: {exc}",
            ) from exc

        format_list = list(formats) if formats else ["markdown"]
        format_payload = [str(name).strip() for name in format_list if str(name).strip()]
        if not format_payload:
            format_payload = ["markdown"]

        response = self._client.post(
            f"{self._api_root}/v2/scrape",
            headers=self._headers(),
            json={
                "url": target,
                "formats": format_payload,
                "onlyMainContent": bool(only_main_content),
            },
            timeout=self._timeout,
        )
        self._raise_for_status(response, action="scrape")
        body = _response_json(response)
        _raise_for_unsuccessful_envelope(body, action="scrape")
        data = body.get("data") if isinstance(body.get("data"), dict) else body
        if not isinstance(data, dict):
            raise FirecrawlProviderError(
                code=FirecrawlErrorCode.BAD_RESPONSE,
                retryable=False,
                message="Malformed Firecrawl scrape response: missing data object",
            )
        markdown = str(data.get("markdown") or data.get("content") or "")
        metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        title = str(
            metadata.get("title")
            or data.get("title")
            or ""
        ).strip()
        final_url = str(
            metadata.get("url")
            or metadata.get("sourceURL")
            or data.get("url")
            or target
        ).strip()
        limit = max(1, int(max_chars))
        truncated = len(markdown) > limit
        clipped = markdown[:limit]
        return {
            "url": final_url,
            "title": title,
            "markdown": clipped,
            "char_count": len(clipped),
            "truncated": truncated,
            "safe_summary": _scrape_summary(title=title, url=final_url, markdown=clipped),
        }

    def healthcheck(self) -> HealthCheckResult:
        """Run a lightweight Firecrawl search health check."""
        try:
            self.search("healthcheck", max_results=1, sources=("web",))
        except Exception as exc:
            return HealthCheckResult(
                provider_name=self._descriptor.name,
                status=ProviderStatus.UNHEALTHY,
                checked_at=utc_now(),
                message=str(exc),
            )
        return HealthCheckResult(
            provider_name=self._descriptor.name,
            status=ProviderStatus.HEALTHY,
            checked_at=utc_now(),
            message="firecrawl search healthy",
        )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _raise_for_status(self, response: Any, *, action: str) -> None:
        status_code = int(getattr(response, "status_code", 0) or 0)
        if status_code == 429:
            raise FirecrawlProviderError(
                code=FirecrawlErrorCode.RATE_LIMITED,
                retryable=True,
                message=f"Firecrawl {action} rate limit exceeded",
                retry_after_seconds=_retry_after_seconds(response),
            )
        if status_code == 408:
            raise FirecrawlProviderError(
                code=FirecrawlErrorCode.TIMEOUT,
                retryable=True,
                message=f"Firecrawl {action} timed out",
            )
        if status_code in (401, 403):
            raise FirecrawlProviderError(
                code=FirecrawlErrorCode.AUTH_FAILED,
                retryable=False,
                message=f"Firecrawl {action} authentication failed",
            )
        if status_code == 400:
            raise FirecrawlProviderError(
                code=FirecrawlErrorCode.BAD_REQUEST,
                retryable=False,
                message=f"Firecrawl {action} bad request",
            )
        if status_code >= 500:
            raise FirecrawlProviderError(
                code=FirecrawlErrorCode.SERVER_ERROR,
                retryable=True,
                message=f"Firecrawl {action} server error: HTTP {status_code}",
            )
        try:
            response.raise_for_status()
        except Exception as exc:
            raise FirecrawlProviderError(
                code=FirecrawlErrorCode.BAD_RESPONSE,
                retryable=False,
                message=f"Firecrawl {action} failed: HTTP {status_code}",
            ) from exc


def _normalize_api_root(base_url: str) -> str:
    """Normalize user-supplied base URLs to the Firecrawl API root."""
    root = str(base_url or DEFAULT_FIRECRAWL_BASE_URL).strip().rstrip("/")
    if not root:
        root = DEFAULT_FIRECRAWL_BASE_URL
    for suffix in (
        "/v2/search",
        "/v2/scrape",
        "/v1/search",
        "/v1/scrape",
        "/v2",
        "/v1",
    ):
        if root.endswith(suffix):
            root = root[: -len(suffix)].rstrip("/")
            break
    parsed = urlparse(root)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError(f"invalid Firecrawl base_url: {base_url}")
    return root


def _retry_after_seconds(response: Any) -> int | None:
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    raw_value = headers.get("Retry-After")
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def _normalize_sources(
    sources: list[str] | tuple[str, ...] | None,
) -> list[str]:
    if sources is None:
        return list(_DEFAULT_SEARCH_SOURCES)
    normalized: list[str] = []
    seen: set[str] = set()
    for item in sources:
        name = str(item or "").strip().lower()
        if name not in {"web", "news", "images"} or name in seen:
            continue
        seen.add(name)
        normalized.append(name)
    return normalized


def _response_json(response: Any) -> dict[str, Any]:
    try:
        payload = response.json()
    except Exception as exc:
        raise FirecrawlProviderError(
            code=FirecrawlErrorCode.BAD_RESPONSE,
            retryable=False,
            message="Malformed Firecrawl response: invalid JSON",
        ) from exc
    if not isinstance(payload, dict):
        raise FirecrawlProviderError(
            code=FirecrawlErrorCode.BAD_RESPONSE,
            retryable=False,
            message="Malformed Firecrawl response: expected object",
        )
    return payload


def _extract_search_items(payload: dict[str, Any]) -> list[Any]:
    """Accept v2 nested data and legacy flat results lists."""
    data = payload.get("data")
    if isinstance(data, dict):
        items: list[Any] = []
        has_source_bucket = False
        for key in ("web", "news", "images"):
            bucket = data.get(key)
            if isinstance(bucket, list):
                has_source_bucket = True
                items.extend(bucket)
        if has_source_bucket:
            return items
        # Some deployments may return data as a bare list under an alias.
    if isinstance(data, list):
        return data
    raw_results = payload.get("results")
    if isinstance(raw_results, list):
        return raw_results
    raise FirecrawlProviderError(
        code=FirecrawlErrorCode.BAD_RESPONSE,
        retryable=False,
        message="Malformed Firecrawl response: missing results list",
    )


def _raise_for_unsuccessful_envelope(
    payload: dict[str, Any],
    *,
    action: str,
) -> None:
    """Reject Firecrawl's structured failure envelope even on HTTP 200."""
    if payload.get("success") is not False:
        return
    raise FirecrawlProviderError(
        code=FirecrawlErrorCode.BAD_RESPONSE,
        retryable=False,
        message=f"Firecrawl {action} returned an unsuccessful response",
    )


def _scrape_summary(*, title: str, url: str, markdown: str) -> str:
    headline = title or url or "page"
    preview = " ".join(markdown.split())[:240]
    if preview:
        return f"Scraped {headline}: {preview}"
    return f"Scraped {headline} (empty body)."
