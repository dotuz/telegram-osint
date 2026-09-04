"""Pure IOC extraction from public text.

``extract_iocs(text)`` returns de-duplicated :class:`IocMatch` objects. It is a
pure function -- no I/O -- so it is trivially unit-tested and safe to run on
untrusted collected content (the text is treated as data, never executed).

Handling:
  * common defang styles are re-fanged first (``hxxp``, ``[.]``, ``(dot)``,
    ``[at]``, ``[:]`` ...);
  * URLs and emails are matched first, then bare domains / IPs that are **not**
    already inside a URL or email span are kept;
  * each URL also yields its host as a ``domain`` IOC, each email its domain
    (``derived_from`` records the origin);
  * hashes are length-anchored so an md5 inside a sha256 is not double-counted.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass

from database.normalize import (
    normalize_cve,
    normalize_domain,
    normalize_email,
    normalize_hash,
    normalize_ip,
    normalize_url,
    normalize_username,
)
from database.types import IOCType

# --------------------------------------------------------------------------- defang

_DEFANG_SUBS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"h(?:xx|XX)p(s?)://", re.IGNORECASE), r"http\1://"),
    (re.compile(r"\[\s*:\s*\]"), ":"),
    (re.compile(r"\[\s*://\s*\]"), "://"),
    (re.compile(r"\s*\[\s*(?:\.|dot)\s*\]\s*", re.IGNORECASE), "."),
    (re.compile(r"\s*\(\s*(?:\.|dot)\s*\)\s*", re.IGNORECASE), "."),
    (re.compile(r"\s*\{\s*(?:\.|dot)\s*\}\s*", re.IGNORECASE), "."),
    (re.compile(r"\s+dot\s+", re.IGNORECASE), "."),
    (re.compile(r"\s*\[\s*(?:@|at)\s*\]\s*", re.IGNORECASE), "@"),
    (re.compile(r"\s*\(\s*(?:@|at)\s*\)\s*", re.IGNORECASE), "@"),
    (re.compile(r"\s+at\s+", re.IGNORECASE), "@"),
)


def refang(text: str) -> str:
    out = text
    for pattern, repl in _DEFANG_SUBS:
        out = pattern.sub(repl, out)
    return out


# --------------------------------------------------------------------------- regexes

_URL_RE = re.compile(r"\b(?:https?|ftp)://[^\s<>\"'`)\]}|]+", re.IGNORECASE)
_TG_URL_RE = re.compile(
    r"\b(?:https?://)?(?:t\.me|telegram\.me|telegram\.dog)/(?:joinchat/|\+)?[A-Za-z0-9_./+\-]+",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@(?:[A-Za-z0-9\-]+\.)+[A-Za-z]{2,}\b")
_IPV4_RE = re.compile(
    r"(?<![\w.])(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(?![\w.])"
)
_IPV6_RE = re.compile(
    r"(?<![:.\w])(?:"
    r"(?:[A-Fa-f0-9]{1,4}:){7}[A-Fa-f0-9]{1,4}"
    r"|(?:[A-Fa-f0-9]{1,4}:){1,7}:"
    r"|(?:[A-Fa-f0-9]{1,4}:){1,6}:[A-Fa-f0-9]{1,4}"
    r"|(?:[A-Fa-f0-9]{1,4}:){1,5}(?::[A-Fa-f0-9]{1,4}){1,2}"
    r"|(?:[A-Fa-f0-9]{1,4}:){1,4}(?::[A-Fa-f0-9]{1,4}){1,3}"
    r"|(?:[A-Fa-f0-9]{1,4}:){1,3}(?::[A-Fa-f0-9]{1,4}){1,4}"
    r"|(?:[A-Fa-f0-9]{1,4}:){1,2}(?::[A-Fa-f0-9]{1,4}){1,5}"
    r"|[A-Fa-f0-9]{1,4}:(?::[A-Fa-f0-9]{1,4}){1,6}"
    r")(?![:.\w])"
)
_DOMAIN_RE = re.compile(r"\b(?:[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,24}\b")
_MD5_RE = re.compile(r"\b[a-fA-F0-9]{32}\b")
_SHA1_RE = re.compile(r"\b[a-fA-F0-9]{40}\b")
_SHA256_RE = re.compile(r"\b[a-fA-F0-9]{64}\b")
_CVE_RE = re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.IGNORECASE)
_TG_USERNAME_RE = re.compile(r"(?<![\w@/])@([A-Za-z][A-Za-z0-9_]{4,31})\b")
_TG_HANDLE_IN_URL_RE = re.compile(
    r"(?:t\.me|telegram\.me|telegram\.dog)/([A-Za-z][A-Za-z0-9_]{4,31})\b", re.IGNORECASE
)

# Bare tokens that look like a domain but are almost always a filename extension.
_DOMAIN_STOP_TLDS = frozenset(
    "php html htm json xml yaml yml toml ini cfg conf txt md rst log csv tsv pdf doc docx "
    "xls xlsx ppt pptx odt rtf py js ts jsx tsx rb go rs java kt cpp cc hpp cs sh bat ps1 "
    "pl lua sql exe dll so dylib bin app msi deb rpm apk dmg iso zip tar gz bz2 xz 7z rar "
    "png jpg jpeg gif bmp svg webp ico mp3 mp4 wav avi mov mkv webm flac woff woff2 ttf "
    "eot css scss less map lock env bak tmp old orig swp class jar war pyc lib dat".split()
)


@dataclass(frozen=True)
class IocMatch:
    ioc_type: str
    value: str
    normalized: str
    start: int
    end: int
    derived_from: str | None = None

    @property
    def key(self) -> tuple[str, str]:
        return (self.ioc_type, self.normalized)


def _valid_ipv6(candidate: str) -> bool:
    try:
        ipaddress.IPv6Address(candidate)
        return True
    except ValueError:
        return False


def _looks_like_domain(value: str) -> bool:
    tld = value.rsplit(".", 1)[-1].lower()
    return tld not in _DOMAIN_STOP_TLDS and not tld.isdigit()


def extract_iocs(text: str) -> list[IocMatch]:  # noqa: C901 - a linear scanner
    if not text:
        return []
    s = refang(text)
    matches: list[IocMatch] = []
    covered: list[tuple[int, int]] = []  # spans owned by URLs / emails / tg-urls

    def add(m: IocMatch) -> None:
        matches.append(m)

    # 1) URLs
    for mo in _URL_RE.finditer(s):
        raw = mo.group(0).rstrip(".,;:!?")
        norm = normalize_url(raw)
        add(IocMatch(IOCType.URL.value, raw, norm, mo.start(), mo.start() + len(raw)))
        covered.append((mo.start(), mo.start() + len(raw)))
        host = _host_of(norm)
        if host and _looks_like_domain(host):
            add(
                IocMatch(
                    IOCType.DOMAIN.value,
                    host,
                    normalize_domain(host),
                    mo.start(),
                    mo.start() + len(raw),
                    derived_from="url",
                )
            )

    # 2) Telegram URLs / handles-in-urls
    for mo in _TG_URL_RE.finditer(s):
        raw = mo.group(0).rstrip(".,;:!?")
        add(IocMatch(IOCType.TELEGRAM_URL.value, raw, normalize_url(raw), mo.start(), mo.end()))
        covered.append((mo.start(), mo.end()))
        hm = _TG_HANDLE_IN_URL_RE.search(raw)
        if hm:
            add(
                IocMatch(
                    IOCType.TELEGRAM_USERNAME.value,
                    hm.group(1),
                    normalize_username(hm.group(1)),
                    mo.start(),
                    mo.end(),
                    derived_from="telegram_url",
                )
            )

    # 3) Emails
    for mo in _EMAIL_RE.finditer(s):
        if _inside(mo.start(), covered):
            continue
        raw = mo.group(0)
        add(IocMatch(IOCType.EMAIL.value, raw, normalize_email(raw), mo.start(), mo.end()))
        covered.append((mo.start(), mo.end()))
        domain = raw.split("@", 1)[1]
        if _looks_like_domain(domain):
            add(
                IocMatch(
                    IOCType.DOMAIN.value,
                    domain,
                    normalize_domain(domain),
                    mo.start(),
                    mo.end(),
                    derived_from="email",
                )
            )

    # 4) Hashes (most specific length first)
    for rx, ioc_type in (
        (_SHA256_RE, IOCType.SHA256),
        (_SHA1_RE, IOCType.SHA1),
        (_MD5_RE, IOCType.MD5),
    ):
        for mo in rx.finditer(s):
            if _inside(mo.start(), covered):
                continue
            add(
                IocMatch(
                    ioc_type.value, mo.group(0), normalize_hash(mo.group(0)), mo.start(), mo.end()
                )
            )
            covered.append((mo.start(), mo.end()))

    # 5) CVEs
    for mo in _CVE_RE.finditer(s):
        add(
            IocMatch(
                IOCType.CVE.value, mo.group(0), normalize_cve(mo.group(0)), mo.start(), mo.end()
            )
        )

    # 6) IPv4 / IPv6 (skip if inside a URL)
    for mo in _IPV4_RE.finditer(s):
        if _inside(mo.start(), covered):
            continue
        try:
            norm = normalize_ip(mo.group(0))
        except ValueError:
            continue
        add(IocMatch(IOCType.IPV4.value, mo.group(0), norm, mo.start(), mo.end()))
    for mo in _IPV6_RE.finditer(s):
        if _inside(mo.start(), covered) or not _valid_ipv6(mo.group(0)):
            continue
        add(
            IocMatch(
                IOCType.IPV6.value,
                mo.group(0),
                normalize_ip(mo.group(0).strip(":")),
                mo.start(),
                mo.end(),
            )
        )

    # 7) Bare domains not already covered / not derived
    have_domain = {m.normalized for m in matches if m.ioc_type == IOCType.DOMAIN.value}
    for mo in _DOMAIN_RE.finditer(s):
        if _inside(mo.start(), covered):
            continue
        value = mo.group(0)
        if not _looks_like_domain(value):
            continue
        norm = normalize_domain(value)
        if norm in have_domain:
            continue
        have_domain.add(norm)
        add(IocMatch(IOCType.DOMAIN.value, value, norm, mo.start(), mo.end()))

    # 8) Telegram @usernames
    for mo in _TG_USERNAME_RE.finditer(s):
        if _inside(mo.start(), covered):
            continue
        add(
            IocMatch(
                IOCType.TELEGRAM_USERNAME.value,
                mo.group(1),
                normalize_username(mo.group(1)),
                mo.start(),
                mo.end(),
            )
        )

    return _dedupe(matches)


def _host_of(normalized_url: str) -> str | None:
    from urllib.parse import urlsplit

    return urlsplit(normalized_url).hostname


def _inside(pos: int, spans: list[tuple[int, int]]) -> bool:
    return any(a <= pos < b for a, b in spans)


def _dedupe(matches: list[IocMatch]) -> list[IocMatch]:
    seen: dict[tuple[str, str], IocMatch] = {}
    for m in sorted(matches, key=lambda x: (x.start, -(x.end - x.start))):
        seen.setdefault(m.key, m)
    return sorted(seen.values(), key=lambda x: (x.start, x.ioc_type))
