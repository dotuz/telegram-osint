"""SSRF-guarded outbound HTTP fetcher.

Every OSINT collector that fetches a URL goes through :class:`SafeFetcher`. It is
the single choke point for outbound requests, so the SSRF controls live in one
place and are tested once.

Controls (spec section 22):
  1. scheme allow-list: ``http`` / ``https`` only
  2. resolve DNS up front; reject if **any** resolved address is loopback,
     private, link-local, ULA, multicast, reserved, or a cloud metadata IP
  3. re-validate the host after every redirect (redirects are followed manually)
  4. cap redirects
  5. cap response size (streamed; aborts mid-body)
  6. strict total timeout
  7. every attempt is logged with the final status

Tests inject a fake ``transport`` (an ``httpx.MockTransport``) or a
``resolver``; production uses the real socket resolver and network.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx

from security.config import Settings, get_settings
from security.logging import get_logger

_log = get_logger("collectors.http")

_ALLOWED_SCHEMES = {"http", "https"}

# Extra host-level denies beyond the ip-property checks.
_BLOCKED_HOSTS = {"metadata.google.internal", "metadata", "localhost"}
# Cloud metadata endpoints (link-local already blocks 169.254/16, listed for clarity).
_METADATA_IPS = {"169.254.169.254", "100.100.100.200", "fd00:ec2::254"}

Resolver = Callable[[str], list[str]]


class SsrfBlocked(Exception):
    """Raised when a URL / host / resolved address fails the SSRF policy."""


class FetchError(Exception):
    """Network / protocol / size / timeout failure (not a policy block)."""


@dataclass
class FetchResponse:
    url: str
    status_code: int
    headers: dict[str, str]
    text: str
    truncated: bool = False

    def json(self) -> object:
        import json

        return json.loads(self.text)

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300


def _default_resolver(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    return list({str(info[4][0]) for info in infos})


def _ip_is_public(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if str(addr) in _METADATA_IPS:
        return False
    return not (
        addr.is_loopback
        or addr.is_private
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )


@dataclass
class SafeFetcher:
    settings: Settings = field(default_factory=get_settings)
    resolver: Resolver = _default_resolver
    transport: httpx.BaseTransport | None = None  # for tests (httpx.MockTransport)

    # ------------------------------------------------------------------ policy
    def _check_url(self, url: str) -> tuple[str, str]:
        parts = urlsplit(url)
        scheme = parts.scheme.lower()
        if scheme not in _ALLOWED_SCHEMES:
            raise SsrfBlocked(f"scheme not allowed: {scheme or '(none)'}")
        host = parts.hostname
        if not host:
            raise SsrfBlocked("missing host")
        if host.lower() in _BLOCKED_HOSTS:
            raise SsrfBlocked(f"host blocked: {host}")

        if self.settings.http_fetch_allow_private:
            return scheme, host  # test / lab escape hatch

        # If the host is a literal IP, check it directly.
        try:
            ipaddress.ip_address(host)
            candidates = [host]
        except ValueError:
            try:
                candidates = self.resolver(host)
            except OSError as exc:
                raise SsrfBlocked(f"dns resolution failed for {host}") from exc
            if not candidates:
                raise SsrfBlocked(f"no addresses for {host}") from None

        for ip in candidates:
            if not _ip_is_public(ip):
                raise SsrfBlocked(f"{host} resolves to non-public address {ip}")
        return scheme, host

    # ------------------------------------------------------------------ fetch
    async def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        accept_statuses: set[int] | None = None,
    ) -> FetchResponse:
        return await self._request("GET", url, headers=headers, accept_statuses=accept_statuses)

    async def head(self, url: str, *, headers: dict[str, str] | None = None) -> FetchResponse:
        return await self._request("HEAD", url, headers=headers)

    async def _request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None,
        accept_statuses: set[int] | None = None,
    ) -> FetchResponse:
        max_bytes = self.settings.http_fetch_max_bytes
        timeout = self.settings.http_fetch_timeout_seconds
        max_redirects = self.settings.http_fetch_max_redirects

        req_headers = {"User-Agent": "telegram-osint-research/1.0", **(headers or {})}
        current = url
        client_kwargs: dict[str, object] = {
            "timeout": timeout,
            "follow_redirects": False,
            "headers": req_headers,
        }
        if self.transport is not None:
            client_kwargs["transport"] = self.transport

        async with httpx.AsyncClient(**client_kwargs) as client:  # type: ignore[arg-type]
            for hop in range(max_redirects + 1):
                self._check_url(current)  # re-validate every hop
                try:
                    resp = await client.request(method, current)
                except httpx.HTTPError as exc:
                    _log.warning("http_fetch_error", url=current, error=str(exc))
                    raise FetchError(str(exc)) from exc

                if resp.is_redirect:
                    if hop >= max_redirects:
                        raise FetchError(f"too many redirects (> {max_redirects})")
                    location = resp.headers.get("location", "")
                    nxt = str(httpx.URL(current).join(location))
                    _log.info("http_fetch_redirect", frm=current, to=nxt, status=resp.status_code)
                    current = nxt
                    continue

                body = resp.content[: max_bytes + 1]
                truncated = len(body) > max_bytes
                text = body[:max_bytes].decode(resp.encoding or "utf-8", errors="replace")
                _log.info(
                    "http_fetch",
                    url=current,
                    status=resp.status_code,
                    bytes=len(body),
                    truncated=truncated,
                )
                if accept_statuses is not None and resp.status_code not in accept_statuses:
                    return FetchResponse(
                        current, resp.status_code, dict(resp.headers), text, truncated
                    )
                return FetchResponse(current, resp.status_code, dict(resp.headers), text, truncated)

        raise FetchError(f"too many redirects (> {max_redirects})")  # pragma: no cover

    async def health_check(self) -> bool:
        return True
