"""Shared SSRF guards for outbound HTTP fetches.

Used by provider base-URL validation and news/document download paths so both
apply the same private-network and scheme policy.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class SSRFError(ValueError):
    """Raised when a URL targets a forbidden scheme, host, or network."""


def assert_public_http_url(
    url: str,
    *,
    allow_local: bool = False,
    resolve_dns: bool = True,
    require_https: bool | None = None,
) -> None:
    """Reject non-http(s) URLs and hosts that resolve to forbidden networks.

    Args:
        url: Absolute URL to validate before connecting.
        allow_local: When True, loopback hosts are permitted (local development).
        resolve_dns: When True, hostnames are resolved and each address checked.
        require_https: Force https when True; when None, http is only allowed if
            ``allow_local`` is True.

    Raises:
        SSRFError: If the URL is unsafe to fetch from the process network namespace.
    """
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise SSRFError("url must be http or https")
    must_https = (not allow_local) if require_https is None else require_https
    if parsed.scheme == "http" and must_https:
        raise SSRFError("url must use https")
    if not parsed.hostname:
        raise SSRFError("url must include a hostname")

    host = parsed.hostname.strip("[]").lower()
    if host == "localhost":
        if allow_local:
            return
        raise SSRFError("url cannot target localhost")

    addresses = _parse_or_resolve_host(host, resolve_dns=resolve_dns)
    for address in addresses:
        if is_forbidden_ip(address):
            if allow_local and address.is_loopback:
                continue
            raise SSRFError(f"url targets forbidden network: {address}")


def is_forbidden_ip(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    """Return whether an IP address is not safe for server-side fetches."""
    return (
        address.is_loopback
        or address.is_link_local
        or address.is_private
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def _parse_or_resolve_host(
    host: str,
    *,
    resolve_dns: bool,
) -> tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]:
    """Parse a literal IP or resolve a hostname to addresses."""
    try:
        return (ipaddress.ip_address(host),)
    except ValueError:
        if not resolve_dns:
            return ()

    resolved: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise SSRFError(f"url host cannot resolve: {host}") from exc
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        try:
            resolved.add(ipaddress.ip_address(sockaddr[0]))
        except ValueError:
            continue
    if not resolved:
        raise SSRFError(f"url host cannot resolve: {host}")
    return tuple(resolved)
