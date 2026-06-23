"""Exchange announcement discovery connector tests."""

from __future__ import annotations

from datetime import UTC, datetime

from margin.news.connectors import SSEAnnouncementConnector, SZSEAnnouncementConnector


class FakeResponse:
    """FakeResponse."""
    def __init__(self, payload: dict):
        """Initialize the instance."""
        self._payload = payload

    def raise_for_status(self):
        """raise for status."""
        return None

    def json(self):
        """json."""
        return self._payload


class FakeClient:
    """FakeClient."""
    def __init__(self, payload: dict):
        """Initialize the instance."""
        self.payload = payload
        self.requests: list[dict] = []

    def get(self, url: str, **kwargs):
        """get."""
        self.requests.append({"url": url, **kwargs})
        return FakeResponse(self.payload)


def test_sse_connector_maps_announcement_payload():
    """SSE adapter must map public announcement JSON into discovered documents."""
    client = FakeClient(
        {
            "result": [
                {
                    "id": "sse-1",
                    "title": "平安银行公告",
                    "url": "https://sse.example/a.pdf",
                    "publishTime": "2026-06-18 09:00:00",
                }
            ],
            "nextCursor": "cursor-2",
        }
    )

    docs = SSEAnnouncementConnector(
        endpoint="https://sse.example/query",
        client=client,
    ).discover(cursor="cursor-1", limit=10)

    assert docs[0].external_id == "sse-1"
    assert docs[0].title == "平安银行公告"
    assert docs[0].published_at == datetime(2026, 6, 18, 9, tzinfo=UTC)
    assert docs[0].cursor == "cursor-2"
    assert client.requests[0]["params"]["cursor"] == "cursor-1"


def test_szse_connector_maps_relative_attach_path():
    """SZSE adapter must convert relative attachment paths to absolute URLs."""
    client = FakeClient(
        {
            "data": [
                {
                    "announcementId": "szse-1",
                    "title": "深交所公告",
                    "attachPath": "/disc/a.pdf",
                    "publishTime": "2026-06-18 10:30:00",
                }
            ],
            "cursor": "cursor-3",
        }
    )

    docs = SZSEAnnouncementConnector(
        endpoint="https://szse.example/api",
        base_url="https://disc.szse.cn",
        client=client,
    ).discover(cursor=None, limit=5)

    assert docs[0].source_url == "https://disc.szse.cn/disc/a.pdf"
    assert docs[0].cursor == "cursor-3"
