"""World graph: nodes with resources, edges with travel cost, and node-local signals.

Hand-rolled, no networkx — at 10-20 nodes the only graph operation needed is
neighbor lookup, and a plain adjacency dict stays printable/inspectable by hand,
which is the actual Phase 0 goal.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum

import constants as C


class ResourceType(str, Enum):
    ORE = "ore"
    FOOD = "food"
    WOOD = "wood"
    TOOL = "tool"


RAW_RESOURCES = (ResourceType.ORE, ResourceType.FOOD, ResourceType.WOOD)


@dataclass
class Signal:
    kind: str          # e.g. "scarce:ore", "rich:food"
    node_id: str
    posted_by: str
    tick: int


@dataclass
class Node:
    id: str
    resource_type: ResourceType | None
    quantity: float
    max_quantity: float
    regen_rate: float
    signals: list[Signal] = field(default_factory=list)


@dataclass
class Edge:
    a: str
    b: str
    cost: float

    def other(self, node_id: str) -> str:
        return self.b if node_id == self.a else self.a


class World:
    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}
        self.adjacency: dict[str, list[Edge]] = {}

    def add_node(self, node: Node) -> None:
        self.nodes[node.id] = node
        self.adjacency.setdefault(node.id, [])

    def add_edge(self, a: str, b: str, cost: float) -> None:
        edge = Edge(a=a, b=b, cost=cost)
        self.adjacency[a].append(edge)
        self.adjacency[b].append(edge)

    def neighbors(self, node_id: str) -> list[Edge]:
        return self.adjacency.get(node_id, [])

    def regen(self) -> None:
        for node in self.nodes.values():
            if node.resource_type is None:
                continue
            node.quantity = min(node.max_quantity, node.quantity + node.regen_rate)

    def prune_signals(self, tick: int) -> None:
        for node in self.nodes.values():
            node.signals = [s for s in node.signals if tick - s.tick <= C.SIGNAL_TTL]

    def is_connected(self) -> bool:
        if not self.nodes:
            return True
        start = next(iter(self.nodes))
        seen = {start}
        stack = [start]
        while stack:
            current = stack.pop()
            for edge in self.neighbors(current):
                nxt = edge.other(current)
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        return seen == set(self.nodes)


def generate_world(num_nodes: int, rng: random.Random) -> World:
    world = World()
    node_ids = [f"n{i}" for i in range(num_nodes)]

    for i, node_id in enumerate(node_ids):
        resource_type = RAW_RESOURCES[i % len(RAW_RESOURCES)]
        max_q = rng.uniform(C.NODE_QUANTITY_MIN, C.NODE_QUANTITY_MAX)
        node = Node(
            id=node_id,
            resource_type=resource_type,
            quantity=max_q,
            max_quantity=max_q,
            regen_rate=rng.uniform(C.NODE_REGEN_MIN, C.NODE_REGEN_MAX),
        )
        world.add_node(node)

    # random recursive tree: connect each node to a random earlier node -> guarantees connectivity
    for i in range(1, num_nodes):
        j = rng.randrange(0, i)
        world.add_edge(node_ids[i], node_ids[j], rng.uniform(C.EDGE_COST_MIN, C.EDGE_COST_MAX))

    # extra random edges so routing has real choices ("top routes" is meaningful, not one forced path)
    extra = int(num_nodes * C.EXTRA_EDGE_RATIO)
    existing = {frozenset((e.a, e.b)) for edges in world.adjacency.values() for e in edges}
    added = 0
    attempts = 0
    while added < extra and attempts < extra * 10 and num_nodes > 2:
        attempts += 1
        a, b = rng.sample(node_ids, 2)
        key = frozenset((a, b))
        if key in existing:
            continue
        world.add_edge(a, b, rng.uniform(C.EDGE_COST_MIN, C.EDGE_COST_MAX))
        existing.add(key)
        added += 1

    return world
