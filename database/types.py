"""Shared enums and small value types used across the schema.

Enums are stored as their string ``value`` in ``String`` columns (not native DB
enums) so migrations stay portable between PostgreSQL and SQLite and new members
can be added without a schema change.
"""

from __future__ import annotations

import enum


class Role(enum.StrEnum):
    USER = "USER"
    ANALYST = "ANALYST"
    ADMIN = "ADMIN"


class SourceType(enum.StrEnum):
    """Where a piece of data came from."""

    TELEGRAM_BOT_API = "telegram_bot_api"
    TELEGRAM_PUBLIC = "telegram_public"
    TELEGRAM_OPERATOR = "telegram_operator"  # explicitly authorized operator account
    GITHUB = "github"
    REDDIT = "reddit"
    X = "x"
    INSTAGRAM = "instagram"
    YOUTUBE = "youtube"
    TIKTOK = "tiktok"
    WEB = "web"
    FORUM = "forum"
    MANUAL = "manual"


class EntityType(enum.StrEnum):
    """Node types in the intelligence graph. Values double as relationship refs."""

    TARGET = "target"
    TELEGRAM_ACCOUNT = "telegram_account"
    TELEGRAM_GROUP = "telegram_group"
    TELEGRAM_CHANNEL = "telegram_channel"
    MESSAGE = "message"
    USERNAME = "username"
    EXTERNAL_ACCOUNT = "external_account"
    DOMAIN = "domain"
    URL = "url"
    IP = "ip"
    IOC = "ioc"
    REPORT = "report"


class RelationshipType(enum.StrEnum):
    USER_HAS_USERNAME = "USER_HAS_USERNAME"
    USERNAME_FOUND_ON = "USERNAME_FOUND_ON"
    USER_POSTED_MESSAGE = "USER_POSTED_MESSAGE"
    MESSAGE_IN_CHANNEL = "MESSAGE_IN_CHANNEL"
    MESSAGE_IN_GROUP = "MESSAGE_IN_GROUP"
    MESSAGE_CONTAINS_DOMAIN = "MESSAGE_CONTAINS_DOMAIN"
    MESSAGE_CONTAINS_IP = "MESSAGE_CONTAINS_IP"
    MESSAGE_CONTAINS_URL = "MESSAGE_CONTAINS_URL"
    MESSAGE_CONTAINS_IOC = "MESSAGE_CONTAINS_IOC"
    MESSAGE_MENTIONS_USERNAME = "MESSAGE_MENTIONS_USERNAME"
    MESSAGE_FORWARDED_FROM = "MESSAGE_FORWARDED_FROM"
    ACCOUNT_LINKED_TO_WEBSITE = "ACCOUNT_LINKED_TO_WEBSITE"
    ACCOUNT_MENTIONS_USER = "ACCOUNT_MENTIONS_USER"
    ACCOUNT_MEMBER_OF_GROUP = "ACCOUNT_MEMBER_OF_GROUP"  # only when publicly exposed
    DOMAIN_REFERENCED_BY_ACCOUNT = "DOMAIN_REFERENCED_BY_ACCOUNT"
    DOMAIN_RESOLVES_TO_IP = "DOMAIN_RESOLVES_TO_IP"
    URL_HAS_DOMAIN = "URL_HAS_DOMAIN"
    TARGET_IS_ACCOUNT = "TARGET_IS_ACCOUNT"
    TARGET_HAS_USERNAME = "TARGET_HAS_USERNAME"


class IOCType(enum.StrEnum):
    IPV4 = "ipv4"
    IPV6 = "ipv6"
    DOMAIN = "domain"
    URL = "url"
    EMAIL = "email"
    MD5 = "md5"
    SHA1 = "sha1"
    SHA256 = "sha256"
    CVE = "cve"
    TELEGRAM_USERNAME = "telegram_username"
    TELEGRAM_URL = "telegram_url"


class TargetKind(enum.StrEnum):
    TELEGRAM_USER = "telegram_user"
    TELEGRAM_ID = "telegram_id"
    USERNAME = "username"
    DOMAIN = "domain"
    EMAIL = "email"
    PHONE = "phone"
    GENERIC = "generic"


class SearchKind(enum.StrEnum):
    USERNAME = "username"
    TELEGRAM_ID = "telegram_id"
    KEYWORD = "keyword"
    DOMAIN = "domain"
    URL = "url"
    EMAIL = "email"
    IP = "ip"
    IOC = "ioc"
    GROUP = "group"
    CHANNEL = "channel"


class TaskStatus(enum.StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    @property
    def is_terminal(self) -> bool:
        return self in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}


class ReportFormat(enum.StrEnum):
    JSON = "json"
    HTML = "html"
    PDF = "pdf"


class Assertion(enum.StrEnum):
    """How a claim is qualified in reports and the AI layer."""

    FACT = "FACT"
    INFERENCE = "INFERENCE"
    UNKNOWN = "UNKNOWN"


CONFIDENCE_MIN = 0
CONFIDENCE_MAX = 100


def clamp_confidence(value: int) -> int:
    return max(CONFIDENCE_MIN, min(CONFIDENCE_MAX, int(value)))
