import pytest

from database.models import Evidence, EvidenceImmutableError, Message, Relationship
from database.repositories import (
    ExternalAccountRepository,
    MessageRepository,
    RelationshipRepository,
    TargetRepository,
    TelegramAccountRepository,
    UserRepository,
)
from database.types import EntityType, RelationshipType, TargetKind
from intelligence.entity_resolution import TargetResolver, merge_entities

pytestmark = pytest.mark.integration


@pytest.fixture
def user(db_session):
    u = UserRepository(db_session).create(email="a@example.com")
    db_session.commit()
    return u


def test_target_resolver_links_username_and_accounts(db_session, user):
    TelegramAccountRepository(db_session).get_or_create(telegram_id=1, username="alice")
    ExternalAccountRepository(db_session).get_or_create("github", "alice")
    db_session.flush()

    target, _ = TargetRepository(db_session, user.id).get_or_create(
        kind=TargetKind.USERNAME, value="@Alice"
    )
    db_session.flush()
    result = TargetResolver(db_session).resolve(target)
    db_session.commit()

    linked_types = {t for t, _ in result.linked}
    assert linked_types == {
        EntityType.USERNAME.value,
        EntityType.TELEGRAM_ACCOUNT.value,
        EntityType.EXTERNAL_ACCOUNT.value,
    }
    edges = db_session.query(Relationship).filter_by(source_id=target.id).all()
    assert {e.rel_type for e in edges} == {
        RelationshipType.TARGET_HAS_USERNAME.value,
        RelationshipType.TARGET_IS_ACCOUNT.value,
    }
    assert db_session.query(Evidence).filter_by(field="resolution").count() >= 3


def test_target_resolver_idempotent(db_session, user):
    TelegramAccountRepository(db_session).get_or_create(telegram_id=1, username="bob")
    target, _ = TargetRepository(db_session, user.id).get_or_create(
        kind=TargetKind.TELEGRAM_USER, value="bob"
    )
    db_session.flush()
    TargetResolver(db_session).resolve(target)
    TargetResolver(db_session).resolve(target)
    db_session.commit()
    assert db_session.query(Relationship).filter_by(source_id=target.id).count() == 1


def test_merge_entities_repoints_everything(db_session):
    keep, _ = TelegramAccountRepository(db_session).get_or_create(telegram_id=1, username="alice")
    drop, _ = TelegramAccountRepository(db_session).get_or_create(username="alice_old")
    other, _ = TelegramAccountRepository(db_session).get_or_create(telegram_id=2, username="bob")

    RelationshipRepository(db_session).observe(
        source_type=EntityType.TELEGRAM_ACCOUNT.value,
        source_id=drop.id,
        target_type=EntityType.TELEGRAM_ACCOUNT.value,
        target_id=other.id,
        rel_type=RelationshipType.ACCOUNT_MENTIONS_USER.value,
        confidence=50,
    )
    ch, _ = TelegramAccountRepository(db_session).get_or_create(telegram_id=99, username="chan")
    MessageRepository(db_session).upsert(
        source_type=EntityType.TELEGRAM_CHANNEL.value,
        source_id=ch.id,
        message_id=9,
        text="x",
        author_account_id=drop.id,
    )
    from database.repositories import EvidenceRepository

    EvidenceRepository(db_session).record(
        entity_type=EntityType.TELEGRAM_ACCOUNT.value,
        entity_id=drop.id,
        field="bio",
        value="old bio",
        source="telegram_public",
        source_type="telegram",
        confidence=60,
    )
    db_session.commit()

    res = merge_entities(
        db_session,
        keep=(EntityType.TELEGRAM_ACCOUNT.value, keep.id),
        drop=(EntityType.TELEGRAM_ACCOUNT.value, drop.id),
    )
    db_session.commit()

    assert res.relationships_repointed == 1
    assert res.messages_repointed == 1
    assert res.evidence_repointed == 1
    assert db_session.query(Message).filter_by(author_account_id=keep.id).count() == 1
    assert db_session.query(Evidence).filter_by(entity_id=drop.id).count() == 0
    assert db_session.query(Evidence).filter_by(entity_id=keep.id).count() == 1
    assert db_session.query(Relationship).filter_by(source_id=drop.id).count() == 0


def test_merge_rejects_cross_type():
    import pytest as _pt

    from database.session import get_sessionmaker

    with _pt.raises(ValueError, match="different types"):
        merge_entities(
            get_sessionmaker()(),
            keep=(EntityType.DOMAIN.value, "a"),
            drop=(EntityType.IP.value, "b"),
        )


def test_evidence_still_immutable_outside_merge(db_session):
    from database.repositories import EvidenceRepository

    acc, _ = TelegramAccountRepository(db_session).get_or_create(telegram_id=1, username="alice")
    _, _c = EvidenceRepository(db_session).record(
        entity_type=EntityType.TELEGRAM_ACCOUNT.value,
        entity_id=acc.id,
        field="bio",
        value="v",
        source="telegram_public",
        source_type="telegram",
        confidence=50,
    )
    db_session.commit()
    ev = db_session.query(Evidence).first()
    ev.entity_id = "somewhere-else"
    with pytest.raises(EvidenceImmutableError):
        db_session.flush()
    db_session.rollback()
