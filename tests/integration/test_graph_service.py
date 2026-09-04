import pytest

from database.repositories import (
    DomainRepository,
    RelationshipRepository,
    TelegramAccountRepository,
    UsernameRepository,
)
from database.types import EntityType, RelationshipType
from intelligence.relationships import GraphService

pytestmark = pytest.mark.integration


@pytest.fixture
def graph(db_session):
    acc, _ = TelegramAccountRepository(db_session).get_or_create(telegram_id=1, username="alice")
    uname, _ = UsernameRepository(db_session).get_or_create("generic", "alice")
    dom, _ = DomainRepository(db_session).get_or_create("alice.example")
    far, _ = DomainRepository(db_session).get_or_create("deep.example")
    rr = RelationshipRepository(db_session)
    rr.observe(
        source_type=EntityType.TELEGRAM_ACCOUNT.value,
        source_id=acc.id,
        target_type=EntityType.USERNAME.value,
        target_id=uname.id,
        rel_type=RelationshipType.USER_HAS_USERNAME.value,
        confidence=90,
    )
    rr.observe(
        source_type=EntityType.TELEGRAM_ACCOUNT.value,
        source_id=acc.id,
        target_type=EntityType.DOMAIN.value,
        target_id=dom.id,
        rel_type=RelationshipType.ACCOUNT_LINKED_TO_WEBSITE.value,
        confidence=70,
    )
    rr.observe(
        source_type=EntityType.DOMAIN.value,
        source_id=dom.id,
        target_type=EntityType.DOMAIN.value,
        target_id=far.id,
        rel_type=RelationshipType.DOMAIN_RESOLVES_TO_IP.value,
        confidence=50,
    )
    db_session.commit()
    return db_session, acc, uname, dom, far


def test_depth_1_stops_at_direct_neighbours(graph):
    session, acc, uname, dom, far = graph
    view = GraphService(session).neighbourhood(EntityType.TELEGRAM_ACCOUNT.value, acc.id, depth=1)
    ids = {n.ref for n in view.nodes}
    assert f"{EntityType.TELEGRAM_ACCOUNT.value}:{acc.id}" in ids
    assert f"{EntityType.DOMAIN.value}:{dom.id}" in ids
    assert f"{EntityType.DOMAIN.value}:{far.id}" not in ids


def test_depth_2_reaches_further(graph):
    session, acc, _u, _d, far = graph
    view = GraphService(session).neighbourhood(EntityType.TELEGRAM_ACCOUNT.value, acc.id, depth=2)
    assert f"{EntityType.DOMAIN.value}:{far.id}" in {n.ref for n in view.nodes}


def test_node_cap_truncates(graph):
    session, acc, *_ = graph
    view = GraphService(session).neighbourhood(
        EntityType.TELEGRAM_ACCOUNT.value, acc.id, depth=3, max_nodes=2
    )
    assert view.truncated is True
    assert len(view.nodes) <= 2


def test_edges_only_between_included_nodes(graph):
    session, acc, *_ = graph
    view = GraphService(session).neighbourhood(EntityType.TELEGRAM_ACCOUNT.value, acc.id, depth=1)
    node_refs = {n.ref for n in view.nodes}
    for e in view.edges:
        assert e.source in node_refs and e.target in node_refs


def test_node_hydration_labels(graph):
    session, acc, *_ = graph
    view = GraphService(session).neighbourhood(EntityType.TELEGRAM_ACCOUNT.value, acc.id, depth=1)
    acc_node = next(n for n in view.nodes if n.entity_type == EntityType.TELEGRAM_ACCOUNT.value)
    assert acc_node.label == "alice"
    assert acc_node.attributes.get("telegram_id") == 1
