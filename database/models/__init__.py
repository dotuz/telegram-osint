"""ORM models.

Importing this module registers every model on ``Base.metadata`` so Alembic
autogenerate and ``create_all`` see the full schema.

Layers:
  * operational: ``Job``, ``AuditLog``
  * identity / workspace: ``User``
  * per-user investigation (scoped to ``user_id``): ``Target``, ``Search``,
    ``SearchResult``, ``Watchlist``, ``Report``
  * shared intelligence graph: ``TelegramAccount``, ``TelegramGroup``,
    ``TelegramChannel``, ``Message``, ``Username``, ``ExternalAccount``,
    ``Domain``, ``URL``, ``IP``, ``IOC``, ``Relationship``, ``Evidence``
"""

from database.models.audit_log import AuditLog
from database.models.evidence import Evidence, EvidenceImmutableError
from database.models.identifiers import ExternalAccount, Username
from database.models.ioc import IOC
from database.models.job import Job, JobState
from database.models.message import Message
from database.models.network import IP, URL, Domain
from database.models.refresh_token import RefreshToken
from database.models.relationship import Relationship
from database.models.report import Report
from database.models.search import Search, SearchResult
from database.models.target import Target
from database.models.telegram import TelegramAccount, TelegramChannel, TelegramGroup
from database.models.user import User
from database.models.watchlist import Watchlist

__all__ = [
    "IOC",
    "IP",
    "URL",
    "AuditLog",
    "Domain",
    "Evidence",
    "EvidenceImmutableError",
    "ExternalAccount",
    "Job",
    "JobState",
    "Message",
    "RefreshToken",
    "Relationship",
    "Report",
    "Search",
    "SearchResult",
    "Target",
    "TelegramAccount",
    "TelegramChannel",
    "TelegramGroup",
    "User",
    "Username",
    "Watchlist",
]
