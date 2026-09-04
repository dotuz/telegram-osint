"""Canonicalisation helpers for identifier fields.

Every dedup-bearing column stores a *normalized* form so that
``@Alice`` / ``alice`` / ``https://Example.COM/`` collapse to one entity. The
original, as-observed value is kept alongside for evidence.
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urlsplit, urlunsplit

_USERNAME_RE = re.compile(r"[^a-z0-9_.]")


_TG_URL_PREFIXES = ("t.me/", "telegram.me/", "telegram.dog/")


def normalize_username(value: str) -> str:
    """Lowercase, strip a leading ``@``, a URL wrapper, and any ``t.me/`` prefix."""
    v = value.strip().lower()
    if v.startswith(("http://", "https://")):
        v = urlsplit(v).netloc + "/" + urlsplit(v).path.lstrip("/")
    for prefix in _TG_URL_PREFIXES:
        if v.startswith(prefix):
            v = v[len(prefix) :]
            break
    v = v.lstrip("@")
    v = v.split("/")[0].split("?")[0]
    return _USERNAME_RE.sub("", v)


def normalize_domain(value: str) -> str:
    v = value.strip().lower().rstrip(".")
    if "://" in v:
        v = urlsplit(v).hostname or v
    if v.startswith("www."):
        v = v[4:]
    return v


def normalize_email(value: str) -> str:
    v = value.strip().lower()
    local, _, domain = v.partition("@")
    return f"{local}@{normalize_domain(domain)}" if domain else v


def normalize_url(value: str) -> str:
    """Lowercase scheme/host, drop fragments and default ports, keep path/query."""
    v = value.strip()
    parts = urlsplit(v if "://" in v else f"http://{v}")
    scheme = (parts.scheme or "http").lower()
    host = (parts.hostname or "").lower()
    if parts.port and not (
        (scheme == "http" and parts.port == 80) or (scheme == "https" and parts.port == 443)
    ):
        host = f"{host}:{parts.port}"
    path = parts.path or "/"
    return urlunsplit((scheme, host, path, parts.query, ""))


def url_hash(normalized_url: str) -> str:
    return hashlib.sha256(normalized_url.encode("utf-8")).hexdigest()


def normalize_ip(value: str) -> str:
    import ipaddress

    return str(ipaddress.ip_address(value.strip()))


def normalize_cve(value: str) -> str:
    return value.strip().upper()


def normalize_hash(value: str) -> str:
    return value.strip().lower()


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
