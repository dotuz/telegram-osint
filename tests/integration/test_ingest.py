import pytest

from collectors.common.interfaces import CollectRequest
from collectors.telegram import TelegramPublicCollector
from collectors.telegram.collector import KIND_CHANNEL, KIND_USER
from database.models import Evidence, Message, Relationship, TelegramAccount, TelegramChannel
from intelligence.ingest import IngestionService
from tests.telegram_fixtures import seeded_source

pytestmark = pytest.mark.integration


@pytest.fixture
def collector():
    return TelegramPublicCollector(seeded_source())


async def test_ingest_user_creates_account_and_evidence(db_session, collector):
    result = await collector.run(CollectRequest(query="alice", kind=KIND_USER))
    summary = IngestionService(db_session).ingest(result)
    db_session.commit()

    assert summary.entities_created == 1
    acc = db_session.query(TelegramAccount).one()
    assert acc.telegram_id == 42
    assert acc.display_name == "Alice Anderson"
    assert db_session.query(Evidence).count() >= 2


async def test_reingest_is_idempotent(db_session, collector):
    for _ in range(2):
        result = await collector.run(CollectRequest(query="alice", kind=KIND_USER))
        IngestionService(db_session).ingest(result)
        db_session.commit()

    assert db_session.query(TelegramAccount).count() == 1
    # evidence dedups on the observation key
    ev_before = db_session.query(Evidence).count()
    result = await collector.run(CollectRequest(query="alice", kind=KIND_USER))
    IngestionService(db_session).ingest(result)
    db_session.commit()
    assert db_session.query(Evidence).count() == ev_before


async def test_ingest_channel_links_messages_to_container(db_session, collector):
    result = await collector.run(CollectRequest(query="opsecnews", kind=KIND_CHANNEL))
    IngestionService(db_session).ingest(result)
    db_session.commit()

    chan = db_session.query(TelegramChannel).one()
    msgs = db_session.query(Message).all()
    assert len(msgs) == 2
    assert {m.source_id for m in msgs} == {chan.id}

    in_channel = db_session.query(Relationship).filter_by(rel_type="MESSAGE_IN_CHANNEL").all()
    assert len(in_channel) == 2
    assert {r.source_type for r in in_channel} == {"message"}


async def test_partial_batch_survives_one_bad_record(db_session, collector):
    result = await collector.run(CollectRequest(query="opsecnews", kind=KIND_CHANNEL))
    # Corrupt one message record's message_id so the upsert fails.
    from dataclasses import replace

    bad = [
        replace(r, natural_key={**r.natural_key, "message_id": "not-an-int"})
        if r.entity_type == "message" and r.natural_key["message_id"] == 11
        else r
        for r in result.records
    ]
    result = replace(result, records=tuple(bad))
    summary = IngestionService(db_session).ingest(result)
    db_session.commit()

    assert db_session.query(Message).count() == 1
    assert "message-2" in " ".join(summary.skipped) or summary.skipped
