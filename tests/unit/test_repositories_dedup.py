import pytest

from database.repositories import (
    DomainRepository,
    IOCRepository,
    TelegramAccountRepository,
    UsernameRepository,
)
from database.types import IOCType

pytestmark = pytest.mark.unit


def test_username_dedup_is_normalized(db_session):
    repo = UsernameRepository(db_session)
    a, created_a = repo.get_or_create("github", "@Alice")
    b, created_b = repo.get_or_create("github", "alice")
    db_session.commit()

    assert created_a is True
    assert created_b is False
    assert a.id == b.id
    assert a.value_normalized == "alice"


def test_same_username_different_platform_is_distinct(db_session):
    repo = UsernameRepository(db_session)
    gh, _ = repo.get_or_create("github", "alice")
    rd, _ = repo.get_or_create("reddit", "alice")
    db_session.commit()
    assert gh.id != rd.id


def test_domain_dedup(db_session):
    repo = DomainRepository(db_session)
    a, _ = repo.get_or_create("https://WWW.Example.com/")
    b, _ = repo.get_or_create("example.com")
    db_session.commit()
    assert a.id == b.id
    assert a.tld == "com"


def test_ioc_dedup_and_observation_count(db_session):
    repo = IOCRepository(db_session)
    a, created = repo.get_or_create(IOCType.DOMAIN, "Evil.com")
    b, created2 = repo.get_or_create("domain", "evil.com")
    db_session.commit()

    assert created is True and created2 is False
    assert a.id == b.id
    assert b.times_observed == 2


def test_telegram_account_dedup_by_id(db_session):
    repo = TelegramAccountRepository(db_session)
    a, _ = repo.get_or_create(telegram_id=42, username="Bob")
    b, _ = repo.get_or_create(telegram_id=42, username="bob_renamed")
    db_session.commit()
    assert a.id == b.id


def test_telegram_account_requires_identifier(db_session):
    with pytest.raises(ValueError, match="required"):
        TelegramAccountRepository(db_session).get_or_create()
