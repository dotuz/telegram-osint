"""Username-OSINT source adapters and the fan-out collector."""

from collectors.username.adapters import (
    GitHubAdapter,
    RedditAdapter,
    TelegramPresenceAdapter,
    WebProbeAdapter,
    default_web_adapters,
)
from collectors.username.base import (
    AdapterResult,
    ProfileFacts,
    UsernameAdapter,
    UsernameAdapterRegistry,
    username_registry,
)
from collectors.username.collector import KIND_USERNAME, UsernameOsintCollector

__all__ = [
    "KIND_USERNAME",
    "AdapterResult",
    "GitHubAdapter",
    "ProfileFacts",
    "RedditAdapter",
    "TelegramPresenceAdapter",
    "UsernameAdapter",
    "UsernameAdapterRegistry",
    "UsernameOsintCollector",
    "WebProbeAdapter",
    "default_web_adapters",
    "username_registry",
]
