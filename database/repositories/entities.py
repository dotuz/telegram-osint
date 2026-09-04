"""Deduplicating access to the shared intelligence-graph entities.

Every ``get_or_create_*`` normalises its input and returns ``(entity, created)``.
Callers must never construct these rows directly -- that would risk duplicates
and skip normalisation.
"""

from __future__ import annotations

from database.models.identifiers import ExternalAccount, Username
from database.models.ioc import IOC
from database.models.network import IP, URL, Domain
from database.models.telegram import TelegramAccount, TelegramChannel, TelegramGroup
from database.normalize import (
    normalize_domain,
    normalize_ip,
    normalize_url,
    normalize_username,
    url_hash,
)
from database.repositories.base import BaseRepository
from database.types import IOCType


class UsernameRepository(BaseRepository[Username]):
    model = Username

    def get_or_create(self, platform: str, value: str) -> tuple[Username, bool]:
        norm = normalize_username(value)
        return self._get_or_create(
            platform=platform,
            value_normalized=norm,
            defaults={"value": value.strip()},
        )


class ExternalAccountRepository(BaseRepository[ExternalAccount]):
    model = ExternalAccount

    def get_or_create(
        self, platform: str, identifier: str, **fields: object
    ) -> tuple[ExternalAccount, bool]:
        norm = normalize_username(identifier)
        return self._get_or_create(
            platform=platform,
            identifier_normalized=norm,
            defaults={"identifier": identifier.strip(), **fields},
        )


class DomainRepository(BaseRepository[Domain]):
    model = Domain

    def get_or_create(self, name: str) -> tuple[Domain, bool]:
        norm = normalize_domain(name)
        tld = norm.rsplit(".", 1)[-1] if "." in norm else None
        return self._get_or_create(
            name_normalized=norm,
            defaults={"name": name.strip(), "tld": tld},
        )


class URLRepository(BaseRepository[URL]):
    model = URL

    def get_or_create(self, raw_url: str) -> tuple[URL, bool]:
        norm = normalize_url(raw_url)
        h = url_hash(norm)
        from urllib.parse import urlsplit

        parts = urlsplit(norm)
        return self._get_or_create(
            url_hash=h,
            defaults={
                "url": raw_url.strip()[:2048],
                "url_normalized": norm[:2048],
                "scheme": parts.scheme or None,
                "host": parts.hostname or None,
            },
        )


class IPRepository(BaseRepository[IP]):
    model = IP

    def get_or_create(self, address: str) -> tuple[IP, bool]:
        import ipaddress

        norm = normalize_ip(address)
        obj = ipaddress.ip_address(norm)
        return self._get_or_create(
            address=norm,
            defaults={"version": obj.version, "is_private": obj.is_private},
        )


class IOCRepository(BaseRepository[IOC]):
    model = IOC

    def get_or_create(self, ioc_type: IOCType | str, value: str) -> tuple[IOC, bool]:
        t = str(IOCType(ioc_type))  # accepts IOCType or its string value
        norm = _normalize_ioc(t, value)
        ioc, created = self._get_or_create(
            ioc_type=t,
            value_normalized=norm,
            defaults={"value": value.strip()},
        )
        if not created:
            ioc.times_observed += 1
        return ioc, created


def _resolve_telegram_entity(repo, telegram_id, username, fields):  # noqa: ANN001, ANN202
    """Dedup a Telegram account/group/channel by ``telegram_id`` OR normalized
    ``username`` -- whichever matches an existing row -- and backfill the other
    key when it was previously unknown.
    """
    from sqlalchemy import select

    norm_username = normalize_username(username) if username else None
    model = repo.model
    session = repo.session

    obj = None
    if telegram_id is not None:
        obj = session.execute(
            select(model).where(model.telegram_id == telegram_id)
        ).scalar_one_or_none()
    if obj is None and norm_username is not None:
        obj = session.execute(
            select(model).where(model.username_normalized == norm_username)
        ).scalar_one_or_none()

    if obj is not None:
        if telegram_id is not None and obj.telegram_id is None:
            obj.telegram_id = telegram_id
        if norm_username is not None and obj.username_normalized is None:
            obj.username = username
            obj.username_normalized = norm_username
        return obj, False

    if telegram_id is None and norm_username is None:
        raise ValueError("telegram_id or username is required")

    defaults = {"username": username, "username_normalized": norm_username, **fields}
    if telegram_id is not None:
        return repo._get_or_create(telegram_id=telegram_id, defaults=defaults)
    return repo._get_or_create(
        username_normalized=norm_username,
        defaults={k: v for k, v in defaults.items() if k != "username_normalized"},
    )


class TelegramAccountRepository(BaseRepository[TelegramAccount]):
    model = TelegramAccount

    def get_or_create(
        self, *, telegram_id: int | None = None, username: str | None = None, **fields: object
    ) -> tuple[TelegramAccount, bool]:
        return _resolve_telegram_entity(self, telegram_id, username, fields)


class TelegramGroupRepository(BaseRepository[TelegramGroup]):
    model = TelegramGroup

    def get_or_create(
        self, *, telegram_id: int | None = None, username: str | None = None, **fields: object
    ) -> tuple[TelegramGroup, bool]:
        return _resolve_telegram_entity(self, telegram_id, username, fields)


class TelegramChannelRepository(BaseRepository[TelegramChannel]):
    model = TelegramChannel

    def get_or_create(
        self, *, telegram_id: int | None = None, username: str | None = None, **fields: object
    ) -> tuple[TelegramChannel, bool]:
        return _resolve_telegram_entity(self, telegram_id, username, fields)


def _normalize_ioc(ioc_type: str, value: str) -> str:
    from database.normalize import normalize_cve, normalize_email, normalize_hash

    match ioc_type:
        case IOCType.DOMAIN.value | IOCType.TELEGRAM_USERNAME.value:
            return normalize_domain(value) if "." in value else normalize_username(value)
        case IOCType.URL.value | IOCType.TELEGRAM_URL.value:
            return normalize_url(value)
        case IOCType.EMAIL.value:
            return normalize_email(value)
        case IOCType.IPV4.value | IOCType.IPV6.value:
            return normalize_ip(value)
        case IOCType.MD5.value | IOCType.SHA1.value | IOCType.SHA256.value:
            return normalize_hash(value)
        case IOCType.CVE.value:
            return normalize_cve(value)
        case _:
            return value.strip().lower()
