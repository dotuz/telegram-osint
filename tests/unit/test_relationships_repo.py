import pytest

from database.repositories import RelationshipRepository
from database.types import EntityType, RelationshipType

pytestmark = pytest.mark.unit


def _observe(session, **overrides):
    kwargs = dict(
        source_type=EntityType.TARGET,
        source_id="t-1",
        target_type=EntityType.USERNAME,
        target_id="u-1",
        rel_type=RelationshipType.TARGET_HAS_USERNAME,
        confidence=40,
    )
    kwargs.update(overrides)
    return RelationshipRepository(session).observe(**kwargs)


def test_observe_creates_then_bumps(db_session):
    edge, created = _observe(db_session)
    db_session.commit()
    first_seen = edge.first_seen
    assert created is True
    assert edge.observation_count == 1

    edge2, created2 = _observe(db_session, confidence=80)
    db_session.commit()

    assert created2 is False
    assert edge2.id == edge.id
    assert edge2.observation_count == 2
    assert edge2.confidence == 80  # max observed
    assert edge2.first_seen == first_seen
    assert edge2.last_seen >= first_seen


def test_reverse_direction_is_a_different_edge(db_session):
    a, _ = _observe(db_session)
    b, created = RelationshipRepository(db_session).observe(
        source_type=EntityType.USERNAME,
        source_id="u-1",
        target_type=EntityType.TARGET,
        target_id="t-1",
        rel_type=RelationshipType.TARGET_HAS_USERNAME,
    )
    db_session.commit()
    assert created is True
    assert a.id != b.id


def test_neighbours_finds_edge_from_either_end(db_session):
    _observe(db_session)
    db_session.commit()
    repo = RelationshipRepository(db_session)
    assert len(repo.neighbours(EntityType.TARGET, "t-1")) == 1
    assert len(repo.neighbours(EntityType.USERNAME, "u-1")) == 1
