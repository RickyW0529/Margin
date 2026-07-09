"""Exchange announcement discovery connector adapters."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from margin.news.discovery import DiscoveredDocument


def _default_client():
    """Return a default ``httpx`` client for exchange discovery requests.

    Returns:
        Any: .
    """
    import httpx

    return httpx.Client(timeout=30.0)


def _parse_datetime(value: str) -> datetime:
    """Parse a date/time string into a timezone-aware UTC datetime.

    Args:
        value: str: .

    Returns:
        datetime: .
    """
    value = value.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return datetime.fromisoformat(value).astimezone(UTC)


class SSEAnnouncementConnector:
    """Fixture-testable SSE announcement discovery adapter.."""

    def __init__(self, *, endpoint: str, client: Any | None = None) -> None:
        """Initialize the SSE connector.

        Args:
            endpoint: str: .
            client: Any | None: .

        Returns:
            None: .
        """
        self._endpoint = endpoint
        self._client = client or _default_client()

    def discover(self, cursor: str | None, limit: int) -> list[DiscoveredDocument]:
        """Fetch and map an SSE announcement page.

        Args:
            cursor: str | None: .
            limit: int: .

        Returns:
            list[DiscoveredDocument]: .
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
    """Fixture-testable SZSE announcement discovery adapter.."""

    def __init__(
        self,
        *,
        endpoint: str,
        base_url: str = "https://disc.szse.cn",
        client: Any | None = None,
    ) -> None:
        """Initialize the SZSE connector.

        Args:
            endpoint: str: .
            base_url: str: .
            client: Any | None: .

        Returns:
            None: .
        """
        self._endpoint = endpoint
        self._base_url = base_url.rstrip("/")
        self._client = client or _default_client()

    def discover(self, cursor: str | None, limit: int) -> list[DiscoveredDocument]:
        """Fetch and map an SZSE announcement page.

        Args:
            cursor: str | None: .
            limit: int: .

        Returns:
            list[DiscoveredDocument]: .
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
                path if path.startswith(("http://", "https://")) else f"{self._base_url}{path}"
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
