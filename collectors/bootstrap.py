"""Register the built-in collectors and adapters on the default registries.

Call :func:`register_default_collectors` once at process start (API / bot / worker).
Idempotent.
"""

from __future__ import annotations

from collectors.common.http import SafeFetcher
from collectors.common.registry import registry
from collectors.telegram.collector import TelegramPublicCollector
from collectors.username.adapters import (
    GitHubAdapter,
    RedditAdapter,
    TelegramPresenceAdapter,
    default_web_adapters,
)
from collectors.username.base import username_registry
from collectors.username.collector import UsernameOsintCollector
from security.logging import get_logger

_log = get_logger("collectors.bootstrap")
_DONE = False


def register_default_collectors() -> None:
    global _DONE
    if _DONE:
        return

    registry.register(TelegramPublicCollector())

    fetcher = SafeFetcher()
    username_registry.clear()
    username_registry.register(GitHubAdapter(fetcher=fetcher))
    username_registry.register(RedditAdapter(fetcher=fetcher))
    username_registry.register(TelegramPresenceAdapter())
    for adapter in default_web_adapters(fetcher):
        username_registry.register(adapter)
    registry.register(UsernameOsintCollector())

    _DONE = True
    _log.info(
        "collectors_registered",
        collectors=[c.name for c in registry.all()],
        username_adapters=[a.platform for a in username_registry.all()],
    )
