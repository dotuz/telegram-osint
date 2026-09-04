import pytest

from collectors.common.interfaces import (
    Collector,
    CollectRequest,
    HealthStatus,
    NormalizedRecord,
    RawBundle,
)
from collectors.common.registry import CollectorRegistry

pytestmark = pytest.mark.unit


class _Boom(Collector):
    name = "boom"
    source_type = "test"
    supported_kinds = frozenset({"x"})

    async def collect(self, request: CollectRequest) -> RawBundle:
        raise RuntimeError("network on fire")

    def normalize(self, raw: RawBundle) -> list[NormalizedRecord]:
        return []

    async def health_check(self) -> HealthStatus:
        return HealthStatus(name=self.name, healthy=True)


class _Ok(Collector):
    name = "ok"
    source_type = "test"
    supported_kinds = frozenset({"x"})

    async def collect(self, request: CollectRequest) -> RawBundle:
        return RawBundle(kind="x", source="test", payload=[{"v": 1}, {"v": 2}])

    def normalize(self, raw: RawBundle) -> list[NormalizedRecord]:
        return [
            NormalizedRecord(ref="a", entity_type="domain", natural_key={"name": "x.com"}),
            NormalizedRecord(ref="b", entity_type="domain", natural_key={"name": "x.com"}),  # dup
            NormalizedRecord(ref="c", entity_type="domain", natural_key={}),  # empty
        ]

    async def health_check(self) -> HealthStatus:
        return HealthStatus(name=self.name, healthy=True)


async def test_run_wraps_collect_exceptions():
    result = await _Boom().run(CollectRequest(query="q", kind="x"))
    assert result.ok is False
    assert "network on fire" in result.error


async def test_run_unsupported_kind_short_circuits():
    result = await _Boom().run(CollectRequest(query="q", kind="other"))
    assert result.ok is False
    assert "unsupported kind" in result.error


async def test_validate_dedups_and_drops_empty_keys():
    result = await _Ok().run(CollectRequest(query="q", kind="x"))
    assert result.ok is True
    assert [r.ref for r in result.records] == ["a"]


def test_registry_dispatch_by_kind():
    reg = CollectorRegistry()
    ok = reg.register(_Ok())
    reg.register(_Boom())
    assert set(reg.for_kind("x")) == {ok, reg.get("boom")}
    assert reg.for_kind("nope") == []


async def test_registry_health_survives_a_broken_collector():
    reg = CollectorRegistry()

    class _Bad(_Ok):
        name = "bad"

        async def health_check(self) -> HealthStatus:
            raise RuntimeError("down")

    reg.register(_Ok())
    reg.register(_Bad())
    statuses = {h.name: h.healthy for h in await reg.health()}
    assert statuses == {"ok": True, "bad": False}
