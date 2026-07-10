"""Firecrawl ToolGateway handlers for agent 舆情 search and scrape."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from margin.agents.security.policies import DataAccessPolicy, ToolPolicy
from margin.agents.tools.specs import ToolCallRequest, ToolSpec
from margin.news.providers.firecrawl import FirecrawlProviderError

ToolHandler = Callable[[ToolCallRequest], dict[str, Any]]

FIRECRAWL_TOOL_VERSION = "v1"
_DEFAULT_MAX_RESULTS = 8
_MAX_RESULTS_CAP = 15
_DEFAULT_MAX_CHARS = 12_000
_MAX_CHARS_CAP = 50_000


def register_firecrawl_tools(catalog: Any, adapter: Any) -> None:
    """Register firecrawl.search / firecrawl.scrape on a ToolCatalog."""
    catalog.register(
        firecrawl_tool_spec("firecrawl.search"),
        firecrawl_search_handler(adapter),
    )
    catalog.register(
        firecrawl_tool_spec("firecrawl.scrape"),
        firecrawl_scrape_handler(adapter),
    )


def firecrawl_tool_spec(tool_name: str) -> ToolSpec:
    """Return the ToolSpec for a Firecrawl agent tool."""
    return ToolSpec(
        tool_name=tool_name,
        tool_version=FIRECRAWL_TOOL_VERSION,
        description=_description(tool_name),
        owner_domain="news",
        input_schema_ref=f"{tool_name}.input",
        output_schema_ref=f"{tool_name}.output",
        input_schema=_input_schema(tool_name),
        output_schema=_output_schema(tool_name),
        required_data_access=(DataAccessPolicy.READ_EVIDENCE,),
        required_write_policy=(),
        required_tool_policy=(ToolPolicy.RETRIEVAL_TOOLS,),
        idempotent=True,
        mutates_state=False,
        timeout_ms=60_000,
        max_output_bytes=96_000,
        returns_raw_payload=False,
        allowed_runtimes=("langgraph", "deterministic"),
    )


def firecrawl_search_handler(adapter: Any) -> ToolHandler:
    """Build a search tool handler bound to a Firecrawl adapter."""

    def handler(request: ToolCallRequest) -> dict[str, Any]:
        query = str(request.input_json.get("query") or "").strip()
        max_results = _bounded_int(
            request.input_json.get("max_results"),
            default=_DEFAULT_MAX_RESULTS,
            minimum=1,
            maximum=_MAX_RESULTS_CAP,
        )
        sources = _string_tuple(request.input_json.get("sources")) or None
        try:
            results = adapter.search(query, max_results=max_results, sources=sources)
        except FirecrawlProviderError as exc:
            return {
                "status": "error",
                "error_code": str(exc.code),
                "retryable": bool(exc.retryable),
                "retry_after_seconds": exc.retry_after_seconds,
                "results": [],
                "result_count": 0,
                "safe_summary": str(exc),
            }
        rows = [
            {
                "url": str(item.get("url") or ""),
                "title": str(item.get("title") or ""),
                "snippet": str(item.get("snippet") or ""),
            }
            for item in results
            if isinstance(item, dict)
        ]
        return {
            "status": "ready" if rows else "empty",
            "query": query,
            "result_count": len(rows),
            "results": rows,
            "safe_summary": (
                f"Firecrawl search returned {len(rows)} result(s) for {query!r}."
                if rows
                else f"Firecrawl search returned no results for {query!r}."
            ),
        }

    return handler


def firecrawl_scrape_handler(adapter: Any) -> ToolHandler:
    """Build a scrape tool handler bound to a Firecrawl adapter."""

    def handler(request: ToolCallRequest) -> dict[str, Any]:
        url = str(request.input_json.get("url") or "").strip()
        only_main_content = bool(request.input_json.get("only_main_content", True))
        max_chars = _bounded_int(
            request.input_json.get("max_chars"),
            default=_DEFAULT_MAX_CHARS,
            minimum=256,
            maximum=_MAX_CHARS_CAP,
        )
        try:
            scraped = adapter.scrape(
                url,
                only_main_content=only_main_content,
                max_chars=max_chars,
            )
        except FirecrawlProviderError as exc:
            return {
                "status": "error",
                "error_code": str(exc.code),
                "retryable": bool(exc.retryable),
                "retry_after_seconds": exc.retry_after_seconds,
                "url": url,
                "title": "",
                "markdown": "",
                "char_count": 0,
                "truncated": False,
                "safe_summary": str(exc),
            }
        return {
            "status": "ready",
            "url": scraped.get("url") or url,
            "title": scraped.get("title") or "",
            "markdown": scraped.get("markdown") or "",
            "char_count": int(scraped.get("char_count") or 0),
            "truncated": bool(scraped.get("truncated")),
            "safe_summary": scraped.get("safe_summary")
            or f"Scraped {url}.",
        }

    return handler


def _description(tool_name: str) -> str:
    if tool_name == "firecrawl.search":
        return (
            "Search the web/news via Firecrawl for public-opinion and news material. "
            "Returns titles, URLs, and snippets only."
        )
    return (
        "Scrape one public HTTPS page via Firecrawl into truncated markdown for "
        "舆情 verification. Private/loopback URLs are blocked."
    )


def _input_schema(tool_name: str) -> dict[str, Any]:
    if tool_name == "firecrawl.search":
        return {
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string", "minLength": 1, "maxLength": 500},
                "max_results": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": _MAX_RESULTS_CAP,
                },
                "sources": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["web", "news", "images"]},
                },
            },
            "additionalProperties": False,
        }
    return {
        "type": "object",
        "required": ["url"],
        "properties": {
            "url": {"type": "string", "minLength": 1},
            "only_main_content": {"type": "boolean"},
            "max_chars": {
                "type": "integer",
                "minimum": 256,
                "maximum": _MAX_CHARS_CAP,
            },
        },
        "additionalProperties": False,
    }


def _output_schema(tool_name: str) -> dict[str, Any]:
    if tool_name == "firecrawl.search":
        return {
            "type": "object",
            "required": ["status", "result_count", "results", "safe_summary"],
            "properties": {
                "status": {"type": "string"},
                "query": {"type": "string"},
                "result_count": {"type": "integer"},
                "results": {"type": "array", "items": {"type": "object"}},
                "safe_summary": {"type": "string"},
                "error_code": {"type": "string"},
                "retryable": {"type": "boolean"},
                "retry_after_seconds": {"type": ["integer", "null"]},
            },
        }
    return {
        "type": "object",
        "required": ["status", "url", "markdown", "safe_summary"],
        "properties": {
            "status": {"type": "string"},
            "url": {"type": "string"},
            "title": {"type": "string"},
            "markdown": {"type": "string"},
            "char_count": {"type": "integer"},
            "truncated": {"type": "boolean"},
            "safe_summary": {"type": "string"},
            "error_code": {"type": "string"},
            "retryable": {"type": "boolean"},
            "retry_after_seconds": {"type": ["integer", "null"]},
        },
    }


def _bounded_int(
    value: object,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    try:
        parsed = int(value) if value is not None else default
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _string_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    if isinstance(value, list | tuple):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return ()
