"""Exchange announcement discovery connector adapters."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from margin.news.discovery import DiscoveredDocument


def _default_client():
    """Return a default ``httpx`` client for exchange discovery requests.

    Returns:
        An ``httpx.Client`` instance with a 30-second timeout.
    """
    import httpx

    return httpx.Client(timeout=30.0)


def _parse_datetime(value: str) -> datetime:
    """Parse a date/time string into a timezone-aware UTC datetime.

    Args:
        value: Date/time string in one of several common formats.

    Returns:
        Timezone-aware UTC datetime.
    """
    value = value.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return datetime.fromisoformat(value).astimezone(UTC)


class SSEAnnouncementConnector:
    """Fixture-testable SSE announcement discovery adapter.

    Attributes:
        _endpoint: URL of the SSE announcement listing endpoint.
        _client: HTTP client used to fetch announcements.
    """

    def __init__(self, *, endpoint: str, client: Any | None = None) -> None:
        """Initialize the SSE connector.

        Args:
            endpoint: URL of the SSE announcement listing endpoint.
            client: Optional pre-configured HTTP client.
        """
        self._endpoint = endpoint
        self._client = client or _default_client()

    def discover(self, cursor: str | None, limit: int) -> list[DiscoveredDocument]:
        """Fetch and map an SSE announcement page.

        Args:
            cursor: Opaque cursor from a previous page, or None for the first page.
            limit: Maximum number of announcements to return.

        Returns:
            List of discovered SSE announcements.
        """
        response = self._client.get(
            self._endpoint,
            params={"cursor": cursor, "limit": limit},
        )
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("result") or payload.get("data") or []
        next_cursor = payload.get("nextCursor") or payload.get("cursor")
        documents: list[DiscoveredDocument] = []
        for row in rows[:limit]:
            documents.append(
                DiscoveredDocument(
                    external_id=str(row.get("id") or row.get("announcementId")),
                    title=str(row.get("title") or ""),
                    source_url=str(row.get("url") or row.get("attachPath") or ""),
                    published_at=_parse_datetime(str(row.get("publishTime") or row.get("date"))),
                    cursor=str(next_cursor) if next_cursor is not None else None,
                    metadata={"exchange": "sse"},
                )
            )
        return documents


class SZSEAnnouncementConnector:
    """Fixture-testable SZSE announcement discovery adapter.

    Attributes:
        _endpoint: URL of the SZSE announcement listing endpoint.
        _base_url: Base URL used to resolve relative attachment paths.
        _client: HTTP client used to fetch announcements.
    """

    def __init__(
        self,
        *,
        endpoint: str,
        base_url: str = "https://disc.szse.cn",
        client: Any | None = None,
    ) -> None:
        """Initialize the SZSE connector.

        Args:
            endpoint: URL of the SZSE announcement listing endpoint.
            base_url: Base URL used to resolve relative attachment paths.
            client: Optional pre-configured HTTP client.
        """
        self._endpoint = endpoint
        self._base_url = base_url.rstrip("/")
        self._client = client or _default_client()

    def discover(self, cursor: str | None, limit: int) -> list[DiscoveredDocument]:
        """Fetch and map an SZSE announcement page.

        Args:
            cursor: Opaque cursor from a previous page, or None for the first page.
            limit: Maximum number of announcements to return.

        Returns:
            List of discovered SZSE announcements.
        """
        response = self._client.get(
            self._endpoint,
            params={"cursor": cursor, "limit": limit},
        )
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("data") or payload.get("result") or []
        next_cursor = payload.get("cursor") or payload.get("nextCursor")
        documents: list[DiscoveredDocument] = []
        for row in rows[:limit]:
            path = str(row.get("attachPath") or row.get("url") or "")
            source_url = (
                path
                if path.startswith(("http://", "https://"))
                else f"{self._base_url}{path}"
            )
            documents.append(
                DiscoveredDocument(
                    external_id=str(row.get("announcementId") or row.get("id")),
                    title=str(row.get("title") or ""),
                    source_url=source_url,
                    published_at=_parse_datetime(str(row.get("publishTime") or row.get("date"))),
                    cursor=str(next_cursor) if next_cursor is not None else None,
                    metadata={"exchange": "szse"},
                )
            )
        return documents
