"""Username-OSINT source adapters.

An adapter answers one question about one platform: *does this username exist
publicly, and what public profile data is visible?* Adapters are registered on
:data:`username_registry`; the :class:`UsernameOsintCollector` fans out to all of
them. Adding a source = one file + one ``register()`` call, no core changes.
"""

from __future__ import annotations

import abc
from collections.abc import Mapping
from dataclasses import dataclass, field

from collectors.common.interfaces import HealthStatus


@dataclass(frozen=True)
class ProfileFacts:
    """Normalised public profile signals used by the confidence engine."""

    display_name: str | None = None
    bio: str | None = None
    website: str | None = None
    email: str | None = None
    location: str | None = None
    avatar_reference: str | None = None
    account_id: str | None = None
    created_at: str | None = None
    extra: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class AdapterResult:
    platform: str
    username: str
    exists: bool
    url: str | None = None
    facts: ProfileFacts | None = None
    # 0-100: adapter's confidence that a public account with this handle exists
    # (NOT that it is the same person as any other account).
    match_confidence: int = 0
    evidence: tuple[str, ...] = ()
    error: str | None = None

    @classmethod
    def not_found(cls, platform: str, username: str, url: str | None = None) -> AdapterResult:
        return cls(platform=platform, username=username, exists=False, url=url)

    @classmethod
    def failed(cls, platform: str, username: str, error: str) -> AdapterResult:
        return cls(platform=platform, username=username, exists=False, error=error)


class UsernameAdapter(abc.ABC):
    #: SourceType value, e.g. "github"
    platform: str = ""
    #: public profile URL template, e.g. "https://github.com/{username}"
    url_template: str | None = None

    def profile_url(self, username: str) -> str | None:
        if self.url_template is None:
            return None
        return self.url_template.format(username=username)

    @abc.abstractmethod
    async def check(self, username: str) -> AdapterResult: ...

    async def health_check(self) -> HealthStatus:
        return HealthStatus(name=self.platform, healthy=True)


class UsernameAdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, UsernameAdapter] = {}

    def register(self, adapter: UsernameAdapter) -> UsernameAdapter:
        if not adapter.platform:
            raise ValueError("adapter.platform is required")
        self._adapters[adapter.platform] = adapter
        return adapter

    def unregister(self, platform: str) -> None:
        self._adapters.pop(platform, None)

    def all(self) -> list[UsernameAdapter]:
        return list(self._adapters.values())

    def get(self, platform: str) -> UsernameAdapter | None:
        return self._adapters.get(platform)

    def clear(self) -> None:
        self._adapters.clear()


username_registry = UsernameAdapterRegistry()
