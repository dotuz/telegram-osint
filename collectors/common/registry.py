"""Collector registry.

New sources register here; the engine and API discover collectors by request
kind without importing them directly.
"""

from __future__ import annotations

from collectors.common.interfaces import Collector, HealthStatus


class CollectorRegistry:
    def __init__(self) -> None:
        self._collectors: dict[str, Collector] = {}

    def register(self, collector: Collector) -> Collector:
        if not collector.name:
            raise ValueError("collector.name is required")
        self._collectors[collector.name] = collector
        return collector

    def unregister(self, name: str) -> None:
        self._collectors.pop(name, None)

    def get(self, name: str) -> Collector | None:
        return self._collectors.get(name)

    def for_kind(self, kind: str) -> list[Collector]:
        return [c for c in self._collectors.values() if c.supports(kind)]

    def all(self) -> list[Collector]:
        return list(self._collectors.values())

    async def health(self) -> list[HealthStatus]:
        out: list[HealthStatus] = []
        for c in self._collectors.values():
            try:
                out.append(await c.health_check())
            except Exception as exc:  # noqa: BLE001
                out.append(HealthStatus(name=c.name, healthy=False, detail=str(exc)))
        return out


#: process-wide default registry
registry = CollectorRegistry()
