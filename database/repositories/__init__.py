"""Repository layer: the only place that builds queries against ORM models.

Application/handler code depends on repositories, never on raw SQLAlchemy
sessions scattered through business logic. All queries are parameterised by
SQLAlchemy; raw SQL string concatenation is forbidden.

  * ``UserRepository`` -- identity / workspace owner
  * shared graph (deduplicating): ``UsernameRepository``,
    ``ExternalAccountRepository``, ``DomainRepository``, ``URLRepository``,
    ``IPRepository``, ``IOCRepository``, ``TelegramAccountRepository``,
    ``TelegramGroupRepository``, ``TelegramChannelRepository``,
    ``MessageRepository``, ``EvidenceRepository`` (append-only),
    ``RelationshipRepository`` (observe-or-bump)
  * per-user (``ScopedRepository``): ``TargetRepository``, ``SearchRepository``,
    ``WatchlistRepository``, ``ReportRepository``
  * operational: ``JobRepository``, ``AuditRepository``
"""

from database.repositories.audit import AuditRepository
from database.repositories.entities import (
    DomainRepository,
    ExternalAccountRepository,
    IOCRepository,
    IPRepository,
    TelegramAccountRepository,
    TelegramChannelRepository,
    TelegramGroupRepository,
    URLRepository,
    UsernameRepository,
)
from database.repositories.evidence import EvidenceRepository
from database.repositories.investigations import (
    ReportRepository,
    ScopedRepository,
    SearchRepository,
    TargetRepository,
    WatchlistRepository,
)
from database.repositories.jobs import IllegalJobStateTransition, JobRepository
from database.repositories.messages import MessageRepository
from database.repositories.refresh_tokens import (
    RefreshTokenRepository,
    RefreshTokenReuseError,
)
from database.repositories.relationships import RelationshipRepository
from database.repositories.users import UserRepository

__all__ = [
    "AuditRepository",
    "DomainRepository",
    "EvidenceRepository",
    "ExternalAccountRepository",
    "IOCRepository",
    "IPRepository",
    "IllegalJobStateTransition",
    "JobRepository",
    "MessageRepository",
    "RefreshTokenRepository",
    "RefreshTokenReuseError",
    "RelationshipRepository",
    "ReportRepository",
    "ScopedRepository",
    "SearchRepository",
    "TargetRepository",
    "TelegramAccountRepository",
    "TelegramChannelRepository",
    "TelegramGroupRepository",
    "URLRepository",
    "UserRepository",
    "UsernameRepository",
    "WatchlistRepository",
]
