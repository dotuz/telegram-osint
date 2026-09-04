import pytest

from collectors.common.interfaces import CollectRequest
from collectors.telegram import NullTelegramSource, TelegramPublicCollector
from collectors.telegram.collector import (
    KIND_CHANNEL,
    KIND_MESSAGE_SEARCH,
    KIND_USER,
)
from database.types import EntityType, RelationshipType
from tests.telegram_fixtures import seeded_source

pytestmark = pytest.mark.unit


@pytest.fixture
def collector():
    return TelegramPublicCollector(seeded_source())


async def test_user_collect_normalizes_profile_with_evidence(collector):
    result = await collector.run(CollectRequest(query="@Alice", kind=KIND_USER))
    assert result.ok
    assert len(result.records) == 1
    rec = result.records[0]
    assert rec.entity_type == EntityType.TELEGRAM_ACCOUNT.value
    assert rec.natural_key["telegram_id"] == 42
    assert rec.attributes["display_name"] == "Alice Anderson"
    fields = {e.field for e in rec.evidence}
    assert "display_name" in fields and "bio" in fields
    assert all(e.source == "telegram_public" for e in rec.evidence)


async def test_channel_collect_returns_chat_and_messages_and_edges(collector):
    result = await collector.run(CollectRequest(query="opsecnews", kind=KIND_CHANNEL, limit=10))
    types = [r.entity_type for r in result.records]
    assert EntityType.TELEGRAM_CHANNEL.value in types
    assert types.count(EntityType.MESSAGE.value) == 2

    edges = {r.rel_type for r in result.relationships}
    assert RelationshipType.MESSAGE_IN_CHANNEL.value in edges


async def test_message_text_iocs_extracted(collector):
    result = await collector.run(CollectRequest(query="opsecnews", kind=KIND_CHANNEL))
    msg = next(
        r
        for r in result.records
        if r.entity_type == EntityType.MESSAGE.value and r.natural_key["message_id"] == 10
    )
    assert set(msg.attributes["urls_json"]) == {
        "https://evil.example",
        "http://evil2.example",
    }
    assert msg.attributes["usernames_json"] == ["leaker"]


async def test_message_search_synthesises_container(collector):
    result = await collector.run(CollectRequest(query="breach dump", kind=KIND_MESSAGE_SEARCH))
    assert any(r.entity_type == EntityType.TELEGRAM_CHANNEL.value for r in result.records), (
        "a container channel should be synthesised for the matched message"
    )
    assert any(r.entity_type == EntityType.MESSAGE.value for r in result.records)


async def test_unavailable_source_degrades_without_raising():
    c = TelegramPublicCollector(NullTelegramSource())
    result = await c.run(CollectRequest(query="x", kind=KIND_USER))
    assert result.ok is False
    assert result.error == "no public Telegram source is configured"
    assert result.records == ()


async def test_unsupported_kind(collector):
    result = await collector.run(CollectRequest(query="x", kind="bogus"))
    assert result.ok is False
    assert "unsupported kind" in result.error


async def test_health_check(collector):
    hs = await collector.health_check()
    assert hs.healthy is True
    assert hs.name == "telegram_public"
