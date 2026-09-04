import pytest

from database.models import (
    IOC,
    IP,
    URL,
    Domain,
    Evidence,
    EvidenceImmutableError,
    Relationship,
    Username,
)
from database.repositories import MessageRepository
from database.types import EntityType
from intelligence.ioc import IocEnricher

pytestmark = pytest.mark.integration

TEXT = (
    "dump at hxxps://evil[.]com/a mirror 185.220.101.1 "
    "hash d41d8cd98f00b204e9800998ecf8427e CVE-2026-12345 ping @leaker_bot"
)


@pytest.fixture
def message(db_session):
    msg, _ = MessageRepository(db_session).upsert(
        source_type=EntityType.TELEGRAM_CHANNEL.value,
        source_id="chan-1",
        message_id=1,
        text=TEXT,
        source_url="https://t.me/x/1",
    )
    db_session.flush()
    return msg


def test_enrich_creates_iocs_typed_entities_and_edges(db_session, message):
    summary = IocEnricher(db_session).enrich_message(
        message_id=message.id, text=TEXT, source="telegram_public", reference="https://t.me/x/1"
    )
    db_session.commit()

    kinds = {i.ioc_type for i in db_session.query(IOC).all()}
    assert {"url", "domain", "ipv4", "md5", "cve", "telegram_username"} <= kinds

    assert db_session.query(Domain).count() >= 1
    assert db_session.query(URL).count() >= 1
    assert db_session.query(IP).count() == 1
    assert db_session.query(Username).filter_by(platform="telegram").count() == 1

    rel_types = {r.rel_type for r in db_session.query(Relationship).all()}
    assert "MESSAGE_CONTAINS_IOC" in rel_types
    assert "MESSAGE_CONTAINS_DOMAIN" in rel_types
    assert "MESSAGE_CONTAINS_IP" in rel_types
    assert "MESSAGE_MENTIONS_USERNAME" in rel_types
    assert summary.iocs_created >= 6


def test_every_ioc_has_evidence_referencing_the_message(db_session, message):
    IocEnricher(db_session).enrich_message(
        message_id=message.id, text=TEXT, source="telegram_public", reference="https://t.me/x/1"
    )
    db_session.commit()

    for ioc in db_session.query(IOC).all():
        ev = (
            db_session.query(Evidence)
            .filter_by(entity_type=EntityType.IOC.value, entity_id=ioc.id)
            .all()
        )
        assert ev, f"IOC {ioc.value} has no evidence"
        assert all(e.reference == "https://t.me/x/1" for e in ev)
        assert all(e.extraction_method == "ioc_regex" for e in ev)


def test_ioc_evidence_is_immutable(db_session, message):
    IocEnricher(db_session).enrich_message(
        message_id=message.id, text=TEXT, source="telegram_public"
    )
    db_session.commit()
    ev = db_session.query(Evidence).first()
    ev.confidence = 1
    with pytest.raises(EvidenceImmutableError):
        db_session.flush()
    db_session.rollback()


def test_enrichment_is_idempotent(db_session, message):
    for _ in range(3):
        IocEnricher(db_session).enrich_message(
            message_id=message.id, text=TEXT, source="telegram_public"
        )
        db_session.commit()
    assert db_session.query(IOC).count() == db_session.query(IOC).distinct().count()
    # a second run creates nothing new
    before = db_session.query(Relationship).count()
    IocEnricher(db_session).enrich_message(
        message_id=message.id, text=TEXT, source="telegram_public"
    )
    db_session.commit()
    assert db_session.query(Relationship).count() == before


def test_domain_ioc_links_to_domain_entity(db_session, message):
    IocEnricher(db_session).enrich_message(
        message_id=message.id, text=TEXT, source="telegram_public"
    )
    db_session.commit()
    dom_ioc = db_session.query(IOC).filter_by(ioc_type="domain").first()
    assert dom_ioc.linked_entity_type == EntityType.DOMAIN.value
    assert db_session.get(Domain, dom_ioc.linked_entity_id) is not None


def test_bio_enrichment_links_account_to_website(db_session):
    from database.repositories import TelegramAccountRepository

    acc, _ = TelegramAccountRepository(db_session).get_or_create(
        telegram_id=7,
        username="alice",
        bio="portfolio at alice.example and https://blog.alice.example",
    )
    db_session.flush()
    IocEnricher(db_session).enrich_entity_text(
        entity_type=EntityType.TELEGRAM_ACCOUNT.value,
        entity_id=acc.id,
        text=acc.bio,
        source="telegram_public",
        field_name="bio",
    )
    db_session.commit()

    rels = {r.rel_type for r in db_session.query(Relationship).filter_by(source_id=acc.id).all()}
    assert "ACCOUNT_LINKED_TO_WEBSITE" in rels
    assert "DOMAIN_REFERENCED_BY_ACCOUNT" in rels
