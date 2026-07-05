"""SSRF guard unit tests (DESIGN.md §1.3 SSRF, §2 risk 3).

Covers each blocked address class, scheme/host validation, the reject-if-any-bad
resolution rule, and the connect-to-validated-IP pin that closes the DNS-rebind
window — all with a mock resolver, no real DNS or sockets.
"""

import httpcore
import pytest

from app.worker import ssrf


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",  # loopback
        "10.0.0.5",  # private A
        "172.16.9.9",  # private B
        "192.168.1.1",  # private C
        "169.254.169.254",  # link-local / cloud metadata
        "0.0.0.0",  # unspecified
        "100.64.0.1",  # CGNAT
        "::1",  # IPv6 loopback
        "fe80::1",  # IPv6 link-local
        "fc00::1",  # IPv6 unique-local
        "::ffff:127.0.0.1",  # IPv4-mapped loopback
        "::ffff:10.0.0.1",  # IPv4-mapped private
    ],
)
def test_blocked_ip_classes(ip: str) -> None:
    assert ssrf.ip_is_blocked(ip) is True


@pytest.mark.parametrize("ip", ["93.184.216.34", "8.8.8.8", "1.1.1.1", "2606:4700:4700::1111"])
def test_public_ips_allowed(ip: str) -> None:
    assert ssrf.ip_is_blocked(ip) is False


async def test_guard_url_rejects_non_http_schemes() -> None:
    for url in ["ftp://example.com/f", "file:///etc/passwd", "gopher://x/", "data:text/x,y"]:
        with pytest.raises(ssrf.SSRFError) as ei:
            await ssrf.guard_url(url)
        assert ei.value.reason == "scheme"


async def test_guard_url_requires_host() -> None:
    with pytest.raises(ssrf.SSRFError) as ei:
        await ssrf.guard_url("http:///nohost")
    assert ei.value.reason == "no_host"


async def test_guard_url_allows_public_host(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(host: str, port: int) -> list[str]:
        return ["93.184.216.34"]

    monkeypatch.setattr(ssrf, "resolve", fake)
    assert await ssrf.guard_url("https://example.com/feed.xml") == "93.184.216.34"


async def test_guard_url_blocks_private_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(host: str, port: int) -> list[str]:
        return ["10.1.2.3"]

    monkeypatch.setattr(ssrf, "resolve", fake)
    with pytest.raises(ssrf.SSRFError) as ei:
        await ssrf.guard_url("https://internal.example/feed")
    assert ei.value.reason == "blocked_ip"


async def test_reject_if_any_resolved_address_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    # A host that mixes a public and a private record (round-robin rebind) is refused.
    async def fake(host: str, port: int) -> list[str]:
        return ["93.184.216.34", "127.0.0.1"]

    monkeypatch.setattr(ssrf, "resolve", fake)
    with pytest.raises(ssrf.SSRFError):
        await ssrf.guard_url("https://mixed.example/feed")


async def test_allowlisted_host_bypasses_private_block(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(host: str, port: int) -> list[str]:
        return ["10.0.0.9"]  # private, normally blocked

    monkeypatch.setattr(ssrf, "resolve", fake)
    # Without the allowlist it's blocked...
    with pytest.raises(ssrf.SSRFError):
        await ssrf.guard_url("http://feedfixture/rss")
    # ...but an allowlisted host resolves through to the private IP.
    ip = await ssrf.guard_url("http://feedfixture/rss", allow_hosts=frozenset({"feedfixture"}))
    assert ip == "10.0.0.9"


async def test_ip_literal_host_is_validated_without_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    async def fake(host: str, port: int) -> list[str]:
        nonlocal called
        called = True
        return ["93.184.216.34"]

    monkeypatch.setattr(ssrf, "resolve", fake)
    with pytest.raises(ssrf.SSRFError):
        await ssrf.guard_url("http://127.0.0.1/feed")  # literal, blocked
    assert called is False  # no DNS lookup for an IP literal


# ── Connect-to-validated-IP pin (defeats DNS rebind) ─────────────────────────


class _FakeStream(httpcore.AsyncNetworkStream):
    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        return b""

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:
        pass

    async def aclose(self) -> None:
        pass

    def get_extra_info(self, info: str) -> object:
        return None


class _FakeInner(httpcore.AsyncNetworkBackend):
    def __init__(self) -> None:
        self.dialed: tuple[str, int] | None = None

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: object = None,
    ) -> httpcore.AsyncNetworkStream:
        self.dialed = (host, port)
        return _FakeStream()

    async def connect_unix_socket(
        self, *args: object, **kwargs: object
    ) -> httpcore.AsyncNetworkStream:
        raise NotImplementedError

    async def sleep(self, seconds: float) -> None:
        pass


async def test_backend_dials_the_validated_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(host: str, port: int) -> list[str]:
        return ["93.184.216.34"]

    monkeypatch.setattr(ssrf, "resolve", fake)
    inner = _FakeInner()
    backend = ssrf._GuardedBackend(inner)
    await backend.connect_tcp("example.com", 443)
    assert inner.dialed == ("93.184.216.34", 443)  # dialed the IP, not the hostname


async def test_backend_blocks_before_dialing_on_rebind(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(host: str, port: int) -> list[str]:
        return ["10.0.0.1"]  # rebound to a private address at connect time

    monkeypatch.setattr(ssrf, "resolve", fake)
    inner = _FakeInner()
    backend = ssrf._GuardedBackend(inner)
    with pytest.raises(ssrf.SSRFError):
        await backend.connect_tcp("rebind.example", 443)
    assert inner.dialed is None  # never opened a socket
