import httpx
import pytest

from collectors.common.http import FetchError, SafeFetcher, SsrfBlocked
from security.config import Settings

pytestmark = pytest.mark.unit


def _fetcher(resolver=None, transport=None, **over):
    s = Settings(_env_file=None, **{"http_fetch_allow_private": False, **over})
    f = SafeFetcher(settings=s)
    if resolver:
        f.resolver = resolver
    if transport:
        f.transport = transport
    return f


OK = httpx.MockTransport(lambda r: httpx.Response(200, text="hello"))


async def test_rejects_non_http_scheme():
    with pytest.raises(SsrfBlocked, match="scheme"):
        await _fetcher(transport=OK).get("file:///etc/passwd")
    with pytest.raises(SsrfBlocked, match="scheme"):
        await _fetcher(transport=OK).get("gopher://evil/")


async def test_blocks_literal_loopback_and_private():
    for url in (
        "http://127.0.0.1/x",
        "http://10.0.0.5/x",
        "http://192.168.1.1/",
        "http://[::1]/",
        "http://169.254.169.254/latest/meta-data",
    ):
        with pytest.raises(SsrfBlocked):
            await _fetcher(transport=OK).get(url)


async def test_blocks_hostname_resolving_to_private():
    f = _fetcher(resolver=lambda h: ["93.184.216.34", "10.1.2.3"], transport=OK)
    with pytest.raises(SsrfBlocked, match="non-public"):
        await f.get("http://sneaky.example/")


async def test_blocks_metadata_hostname():
    with pytest.raises(SsrfBlocked):
        await _fetcher(transport=OK).get("http://metadata.google.internal/")


async def test_allows_public_host():
    f = _fetcher(resolver=lambda h: ["93.184.216.34"], transport=OK)
    resp = await f.get("http://example.com/")
    assert resp.status_code == 200
    assert resp.text == "hello"


async def test_redirect_to_private_is_blocked():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "start.example":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/secret"})
        return httpx.Response(200, text="should not reach")

    f = _fetcher(resolver=lambda h: ["93.184.216.34"], transport=httpx.MockTransport(handler))
    with pytest.raises(SsrfBlocked):
        await f.get("http://start.example/")


async def test_too_many_redirects():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://example.com/next"})

    f = _fetcher(
        resolver=lambda h: ["93.184.216.34"],
        transport=httpx.MockTransport(handler),
        http_fetch_max_redirects=2,
    )
    with pytest.raises(FetchError, match="too many redirects"):
        await f.get("http://example.com/")


async def test_response_size_capped():
    big = "A" * 5000
    t = httpx.MockTransport(lambda r: httpx.Response(200, text=big))
    f = _fetcher(resolver=lambda h: ["93.184.216.34"], transport=t, http_fetch_max_bytes=100)
    resp = await f.get("http://example.com/")
    assert resp.truncated is True
    assert len(resp.text) == 100


async def test_allow_private_escape_hatch():
    f = _fetcher(transport=OK, http_fetch_allow_private=True)
    resp = await f.get("http://127.0.0.1/x")
    assert resp.status_code == 200
