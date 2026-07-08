"""SSRF guard for the fetcher (DESIGN.md §1.3 SSRF, §2 risk 3).

Public users make *our server* fetch arbitrary URLs, so every fetch — and every
redirect hop — must be validated before a socket is opened. The rules:

* only ``http``/``https`` schemes;
* resolve DNS first, then reject any address in a private/loopback/link-local/
  metadata/reserved range (IPv4, IPv6, and IPv4-mapped IPv6);
* connect to the *resolved* IP, never a second lookup — closing the DNS-rebind
  window where validation and connection resolve to different addresses.

The last point is enforced by :class:`SSRFGuardedTransport`: its network backend
resolves + validates and then dials the exact IP it validated. :func:`guard_url`
is the cheap pre-flight the fetch loop calls before each hop.
"""

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

import httpcore
import httpx

ALLOWED_SCHEMES = ("http", "https")


class SSRFError(Exception):
    """A URL/host was refused by the SSRF guard. ``reason`` is a short code."""

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        super().__init__(detail or reason)


_IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


def _unwrap(ip: _IPAddress) -> _IPAddress:
    """Collapse IPv4-mapped IPv6 (``::ffff:a.b.c.d``) to its IPv4 form."""
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


def ip_is_blocked(raw_ip: str) -> bool:
    """True if ``raw_ip`` is anything but a globally-routable public address."""
    ip = _unwrap(ipaddress.ip_address(raw_ip))
    return (
        not ip.is_global  # catch-all: CGNAT, benchmarking, documentation, etc.
        or ip.is_private
        or ip.is_loopback
        or ip.is_link_local  # 169.254/16 & fe80::/10 — includes cloud metadata
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


async def resolve(host: str, port: int) -> list[str]:
    """Resolve ``host`` to a list of IP strings (async, non-blocking).

    Split out as the DNS seam so tests can substitute a mock resolver.
    """
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    # Preserve order, drop duplicates.
    seen: dict[str, None] = {}
    for info in infos:
        # sockaddr[0] is the address string; newer typeshed widens the sockaddr
        # union so its first element is str | int — coerce to keep it a str key.
        seen.setdefault(str(info[4][0]), None)
    return list(seen)


async def resolve_and_validate(
    host: str, port: int, *, allow_hosts: frozenset[str] = frozenset()
) -> list[str]:
    """Resolve ``host`` and validate every address; return the allowed IPs.

    A host with *any* blocked address is refused outright (defeats round-robin /
    rebind tricks that mix a public and a private record). A host in ``allow_hosts``
    skips the private-range block (still resolved) — for trusted internal feeds.
    """
    # Accept IP literals without a DNS round-trip, but still validate them.
    try:
        ipaddress.ip_address(host)
        candidates = [host]
    except ValueError:
        candidates = await resolve(host, port)
    if not candidates:
        raise SSRFError("dns", f"{host!r} did not resolve")
    if host in allow_hosts:
        return candidates
    for ip in candidates:
        if ip_is_blocked(ip):
            raise SSRFError("blocked_ip", f"{host!r} resolves to disallowed address {ip}")
    return candidates


async def guard_url(url: str, *, allow_hosts: frozenset[str] = frozenset()) -> str:
    """Validate a URL's scheme + resolved host; return the IP to connect to.

    Raises :class:`SSRFError` on a bad scheme, missing host, or disallowed address.
    """
    parts = urlsplit(url)
    if parts.scheme not in ALLOWED_SCHEMES:
        raise SSRFError("scheme", f"scheme {parts.scheme!r} is not allowed")
    host = parts.hostname
    if not host:
        raise SSRFError("no_host", f"no host in {url!r}")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    ips = await resolve_and_validate(host, port, allow_hosts=allow_hosts)
    return ips[0]


class _GuardedBackend(httpcore.AsyncNetworkBackend):
    """Network backend that resolves+validates a host and dials the validated IP.

    Because resolution and connection happen here, atomically, there is no second
    lookup for an attacker to rebind between (DESIGN.md §1.3).
    """

    def __init__(
        self, inner: httpcore.AsyncNetworkBackend, allow_hosts: frozenset[str] = frozenset()
    ) -> None:
        self._inner = inner
        self._allow_hosts = allow_hosts

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: object = None,
    ) -> httpcore.AsyncNetworkStream:
        ips = await resolve_and_validate(host, port, allow_hosts=self._allow_hosts)
        return await self._inner.connect_tcp(
            ips[0],
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,  # type: ignore[arg-type]
        )

    async def connect_unix_socket(
        self, path: str, timeout: float | None = None, socket_options: object = None
    ) -> httpcore.AsyncNetworkStream:
        raise SSRFError("unix_socket", "unix sockets are not allowed")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


class SSRFGuardedTransport(httpx.AsyncHTTPTransport):
    """``AsyncHTTPTransport`` whose TCP connections are pinned to a validated IP."""

    def __init__(self, *, allow_hosts: frozenset[str] = frozenset(), **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        # Wrap the pool's backend so every new connection is validated + pinned.
        self._pool._network_backend = _GuardedBackend(self._pool._network_backend, allow_hosts)
