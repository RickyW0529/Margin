"""Tests for ``margin.news.robots`` robots.txt compliance.

These tests verify that ``RobotsChecker`` correctly applies robots.txt rules,
caches fetched robots.txt content per origin, and rejects unsupported URL schemes
before acquisition.
"""

from __future__ import annotations

import pytest

from margin.news.acquirer import ComplianceError
from margin.news.robots import RobotsChecker


def test_robots_checker_enforces_disallow_and_caches_by_origin():
    """Allowed and disallowed paths are enforced and robots.txt is fetched once per origin.

    Verifies that:
    - a path not matching a ``Disallow`` rule is allowed;
    - a path matching ``Disallow`` is rejected;
    - a more specific ``Allow`` inside a disallowed prefix is allowed;
    - the robots.txt fetcher is invoked exactly one time for the origin.
    """
    calls: list[str] = []

    def fetcher(url: str) -> tuple[int, bytes]:
        """Fake robots.txt fetcher that records each requested URL.

        Args:
            url: The robots.txt URL being fetched.

        Returns:
            A tuple of HTTP status code and raw robots.txt body.
        """
        calls.append(url)
        return (
            200,
            b"User-agent: *\nDisallow: /private\nAllow: /private/public\n",
        )

    checker = RobotsChecker(fetcher=fetcher, user_agent="MarginBot")

    assert checker.allowed("https://example.com/news") is True
    assert checker.allowed("https://example.com/private/earnings") is False
    assert checker.allowed("https://example.com/private/public/notice") is True
    assert calls == ["https://example.com/robots.txt"]


def test_robots_checker_rejects_invalid_schemes():
    """Non-HTTP/HTTPS schemes are rejected with a compliance error.

    Verifies that ``assert_allowed`` raises ``ComplianceError`` when the URL
    scheme is not supported for compliant web acquisition.
    """
    checker = RobotsChecker(fetcher=lambda url: (404, b""))

    with pytest.raises(ComplianceError, match="Unsupported URL scheme"):
        checker.assert_allowed("ftp://example.com/file")
