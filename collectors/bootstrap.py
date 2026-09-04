"""Register the built-in collectors on the default registry.

Call :func:`register_default_collectors` once at process start (API / bot / worker).
Idempotent.
"""

from __future__ import annotations

from collectors.common.registry import registry
from collectors.telegram.collector import TelegramPublicCollector
from security.logging import get_logger

_log = get_logger("collectors.bootstrap")
_DONE = False


def register_default_collectors() -> None:
    global _DONE
    if _DONE:
        return
    registry.register(TelegramPublicCollector())
    # Phase 6: github, reddit, web, username adapters register here too.
    _DONE = True
    _log.info("collectors_registered", collectors=[c.name for c in registry.all()])
