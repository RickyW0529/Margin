"""Robots.txt compliance checks for public web acquisition.

Fetches and parses robots.txt files with longest-prefix Allow/Disallow semantics, then decides
whether a given URL may be fetched. Unknown or unreachable robots.txt files are treated as
allow-all for safety.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

from margin.news.acquirer import ComplianceError


class RobotsFetcher(Protocol):
    """Callable that fetches robots.txt bytes.

    Implementations should return the HTTP status code and raw response body for a robots.txt
    URL.
    """

    def __call__(self, url: str) -> tuple[int, bytes]: ...


def _default_fetcher(url: str) -> tuple[int, bytes]:
    """Fetch robots.txt using ``httpx`` with redirects enabled.

    Args:
        url: Full robots.txt URL.

    Returns:
        Tuple of HTTP status code and response body bytes.
    """
    import httpx

    response = httpx.get(url, timeout=10, follow_redirects=True)
    return response.status_code, response.content


@dataclass
class RobotsRules:
    """Parsed robots rules for one origin.

    Attributes:
        allows: List of Allow path prefixes.
        disallows: List of Disallow path prefixes.
    """

    allows: list[str]
    disallows: list[str]

    def can_fetch(self, path: str) -> bool:
        """Apply longest-prefix Allow/Disallow semantics.

        Args:
            path: URL path to test.

        Returns:
            True if the path is allowed, False otherwise.
        """
        matches: list[tuple[int, bool]] = []
        for rule in self.allows:
            if path.startswith(rule):
                matches.append((len(rule), True))
        for rule in self.disallows:
            if rule and path.startswith(rule):
                matches.append((len(rule), False))
        if not matches:
            return True
        return sorted(matches, key=lambda item: item[0], reverse=True)[0][1]


@dataclass
class RobotsChecker:
    """Cached robots.txt checker.

    Fetches and parses robots.txt once per origin, then answers fetch permission queries for
    arbitrary URLs on that origin.

    Attributes:
        fetcher: Callable used to retrieve robots.txt.
        user_agent: User-agent string to match in robots.txt (currently wildcard ``*``).
        _cache: Internal cache mapping origin strings to parsed ``RobotsRules``.
    """

    fetcher: RobotsFetcher = _default_fetcher
    user_agent: str = "MarginBot/0.1"

    def __post_init__(self) -> None:
        """Initialize the per-origin rules cache."""
        self._cache: dict[str, RobotsRules] = {}

    def allowed(self, url: str) -> bool:
        """Return whether ``url`` can be fetched under robots.txt.

        Args:
            url: URL to test.

        Returns:
            True if the URL scheme is HTTP/HTTPS and the path is allowed.
        """
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return False
        parser = self._parser_for(parsed.scheme, parsed.netloc)
        path = parsed.path or "/"
        return parser.can_fetch(path)

    def assert_allowed(self, url: str) -> None:
        """Raise ``ComplianceError`` if the URL is not allowed.

        Args:
            url: URL to validate.

        Raises:
            ComplianceError: If the scheme is unsupported or robots.txt disallows the URL.
        """
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise ComplianceError(f"Unsupported URL scheme for '{url}'")
        if not self.allowed(url):
            raise ComplianceError(f"robots.txt disallows '{url}'")

    def _parser_for(self, scheme: str, netloc: str) -> RobotsRules:
        """Fetch, parse, and cache robots.txt for an origin.

        Args:
            scheme: URL scheme (http or https).
            netloc: Network location (host with optional port).

        Returns:
            Parsed ``RobotsRules`` for the origin.
        """
        origin = f"{scheme}://{netloc}"
        if origin in self._cache:
            return self._cache[origin]

        robots_url = f"{origin}/robots.txt"
        try:
            status, content = self.fetcher(robots_url)
        except Exception:
            status, content = 404, b""

        if status == 200:
            parser = self._parse_rules(content.decode("utf-8", errors="replace"))
        else:
            parser = RobotsRules(allows=["/"], disallows=[])

        self._cache[origin] = parser
        return parser

    @staticmethod
    def _parse_rules(content: str) -> RobotsRules:
        """Parse a robots.txt body into Allow/Disallow rules for user-agent ``*``.

        Args:
            content: Decoded robots.txt content.

        Returns:
            Parsed ``RobotsRules``.
        """
        allows: list[str] = []
        disallows: list[str] = []
        active = False
        for line in content.splitlines():
            stripped = line.split("#", 1)[0].strip()
            if not stripped or ":" not in stripped:
                continue
            key, value = stripped.split(":", 1)
            key = key.strip().lower()
            value = value.strip() or "/"
            if key == "user-agent":
                active = value == "*"
                continue
            if not active:
                continue
            if key == "allow":
                allows.append(value)
            elif key == "disallow":
                disallows.append(value)
        return RobotsRules(allows=allows, disallows=disallows)
