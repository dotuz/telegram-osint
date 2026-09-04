"""Entity-graph traversal.

Builds a bounded neighbourhood view (nodes + edges) around any entity or around
a target's resolved entities. BFS with hard depth and node caps so a hub node
can't explode the response.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models.identifiers import ExternalAccount, Username
from database.models.ioc import IOC
from database.models.message import Message
from database.models.network import IP, URL, Domain
from database.models.relationship import Relationship
from database.models.target import Target
from database.models.telegram import TelegramAccount, TelegramChannel, TelegramGroup
from database.types import EntityType, RelationshipType

_MAX_NODES = 200
_MAX_DEPTH = 3

# EntityType value -> (model, attribute to use as a human label)
_MODELS: dict[str, tuple[type, tuple[str, ...]]] = {
    EntityType.TARGET.value: (Target, ("label", "value")),
    EntityType.TELEGRAM_ACCOUNT.value: (TelegramAccount, ("display_name", "username")),
    EntityType.TELEGRAM_GROUP.value: (TelegramGroup, ("title", "username")),
    EntityType.TELEGRAM_CHANNEL.value: (TelegramChannel, ("title", "username")),
    EntityType.MESSAGE.value: (Message, ("message_id",)),
    EntityType.USERNAME.value: (Username, ("value",)),
    EntityType.EXTERNAL_ACCOUNT.value: (ExternalAccount, ("display_name", "identifier")),
    EntityType.DOMAIN.value: (Domain, ("name",)),
    EntityType.URL.value: (URL, ("url",)),
    EntityType.IP.value: (IP, ("address",)),
    EntityType.IOC.value: (IOC, ("value",)),
}

_TARGET_REL_TYPES = (
    RelationshipType.TARGET_IS_ACCOUNT.value,
    RelationshipType.TARGET_HAS_USERNAME.value,
)


@dataclass
class GraphNode:
    entity_type: str
    entity_id: str
    label: str
    attributes: dict = field(default_factory=dict)

    @property
    def ref(self) -> str:
        return f"{self.entity_type}:{self.entity_id}"


@dataclass
class GraphEdge:
    source: str  # "type:id"
    target: str
    rel_type: str
    confidence: int
    observation_count: int
    first_seen: str | None
    last_seen: str | None


@dataclass
class GraphView:
    root: str
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    truncated: bool = False

    def as_dict(self) -> dict:
        return {
            "root": self.root,
            "truncated": self.truncated,
            "nodes": [
                {"id": n.ref, "type": n.entity_type, "label": n.label, "attributes": n.attributes}
                for n in self.nodes
            ],
            "edges": [
                {
                    "source": e.source,
                    "target": e.target,
                    "type": e.rel_type,
                    "confidence": e.confidence,
                    "observation_count": e.observation_count,
                    "first_seen": e.first_seen,
                    "last_seen": e.last_seen,
                }
                for e in self.edges
            ],
        }


class GraphService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def neighbourhood(
        self,
        entity_type: str,
        entity_id: str,
        *,
        depth: int = 1,
        max_nodes: int = _MAX_NODES,
    ) -> GraphView:
        depth = max(1, min(_MAX_DEPTH, depth))
        return self._bfs([(entity_type, entity_id)], f"{entity_type}:{entity_id}", depth, max_nodes)

    def for_target(
        self, target_id: str, *, depth: int = 2, max_nodes: int = _MAX_NODES
    ) -> GraphView:
        seeds = [(EntityType.TARGET.value, target_id)]
        seeds += self.resolved_entities(target_id)
        depth = max(1, min(_MAX_DEPTH, depth))
        return self._bfs(seeds, f"{EntityType.TARGET.value}:{target_id}", depth, max_nodes)

    def resolved_entities(self, target_id: str) -> list[tuple[str, str]]:
        rows = self.session.execute(
            select(Relationship.target_type, Relationship.target_id).where(
                Relationship.source_type == EntityType.TARGET.value,
                Relationship.source_id == target_id,
                Relationship.rel_type.in_(_TARGET_REL_TYPES),
            )
        ).all()
        return [(t, i) for t, i in rows]

    # ------------------------------------------------------------------ internal
    def _bfs(
        self,
        seeds: list[tuple[str, str]],
        root_ref: str,
        depth: int,
        max_nodes: int,
    ) -> GraphView:
        view = GraphView(root=root_ref)
        visited: set[tuple[str, str]] = set()
        seen_edges: set[tuple] = set()
        queue: deque[tuple[tuple[str, str], int]] = deque((s, 0) for s in seeds)

        while queue:
            (etype, eid), d = queue.popleft()
            if (etype, eid) in visited:
                continue
            visited.add((etype, eid))
            view.nodes.append(self._hydrate(etype, eid))
            if len(visited) >= max_nodes:
                view.truncated = True
                break
            if d >= depth:
                continue

            for rel in self._edges_for(etype, eid):
                key = (rel.source_type, rel.source_id, rel.target_type, rel.target_id, rel.rel_type)
                if key not in seen_edges:
                    seen_edges.add(key)
                    view.edges.append(
                        GraphEdge(
                            source=f"{rel.source_type}:{rel.source_id}",
                            target=f"{rel.target_type}:{rel.target_id}",
                            rel_type=rel.rel_type,
                            confidence=rel.confidence,
                            observation_count=rel.observation_count,
                            first_seen=rel.first_seen.isoformat() if rel.first_seen else None,
                            last_seen=rel.last_seen.isoformat() if rel.last_seen else None,
                        )
                    )
                other = (
                    (rel.target_type, rel.target_id)
                    if (rel.source_type, rel.source_id) == (etype, eid)
                    else (rel.source_type, rel.source_id)
                )
                if other not in visited:
                    queue.append((other, d + 1))

        # keep only edges whose both ends are in the node set
        node_refs = {n.ref for n in view.nodes}
        view.edges = [e for e in view.edges if e.source in node_refs and e.target in node_refs]
        return view

    def _edges_for(self, etype: str, eid: str) -> list[Relationship]:
        from sqlalchemy import or_

        stmt = (
            select(Relationship)
            .where(
                or_(
                    (Relationship.source_type == etype) & (Relationship.source_id == eid),
                    (Relationship.target_type == etype) & (Relationship.target_id == eid),
                )
            )
            .order_by(Relationship.confidence.desc())
            .limit(100)
        )
        return list(self.session.execute(stmt).scalars().all())

    def _hydrate(self, etype: str, eid: str) -> GraphNode:
        spec = _MODELS.get(etype)
        if spec is None:
            return GraphNode(etype, eid, label=eid[:8])
        model, label_attrs = spec
        obj = self.session.get(model, eid)
        if obj is None:
            return GraphNode(etype, eid, label=f"{etype}:{eid[:8]}")
        label = next(
            (str(getattr(obj, a)) for a in label_attrs if getattr(obj, a, None) not in (None, "")),
            f"{etype}:{eid[:8]}",
        )
        attrs = {
            a: getattr(obj, a)
            for a in (
                "username",
                "telegram_id",
                "ioc_type",
                "participants_count",
                "value_normalized",
            )
            if getattr(obj, a, None) is not None
        }
        return GraphNode(etype, eid, label=label, attributes=attrs)
