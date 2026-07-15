"""Utility scoring and action selection for crowd agents.

Greedy "utility AI" (Sims-style scored actions), no planning/search beyond a
1-hop move lookahead. Every score ultimately derives from marginal_value():
diminishing returns as an agent holds more of something. That single formula
is what makes trade rational for non-reasoning agents without any negotiation
logic — an agent with 5 food and 0 wood values wood more than its 6th food.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional

import constants as C
from agents import AgentState
from world import Node, ResourceType, RAW_RESOURCES, World

TRADE_ENABLED = True  # flipped off by run.py's --no-trade negative control


@dataclass
class Intent:
    action: str
    target: Optional[str] = None       # node id (Move/Gather/Signal) or agent id (Trade)
    resource: Optional[str] = None      # resource involved (Gather/Consume) or signal kind
    give: Optional[str] = None          # Trade: resource I give
    give_amt: float = 0.0
    want: Optional[str] = None          # Trade: resource I want
    want_amt: float = 0.0


def hunger_pressure(agent: AgentState) -> float:
    return (agent.hunger / 100.0) ** 2


def energy_pressure(agent: AgentState) -> float:
    return ((100.0 - agent.energy) / 100.0) ** 2


def marginal_value(agent: AgentState, resource: ResourceType) -> float:
    if resource == ResourceType.TOOL:
        # tools are equipped capital (tool_durability), not an inventory item
        held = 1.0 if agent.tool_durability > 0 else 0.0
        return C.TOOL_BASE_VALUE / (1.0 + held)

    held = agent.held(resource)
    if resource == ResourceType.FOOD:
        base = C.FOOD_BASE_VALUE * (1.0 + hunger_pressure(agent))
    else:  # ORE or WOOD
        base = C.RAW_BASE_VALUE
        other = ResourceType.WOOD if resource == ResourceType.ORE else ResourceType.ORE
        if agent.held(other) >= C.TRADE_MIN_HELD:
            base += C.CRAFT_COMPLEMENT_BONUS
    return base / (1.0 + held)


def _gather_yield_multiplier(agent: AgentState, resource_type: ResourceType) -> float:
    mult = (C.SPECIALTY_GATHER_MULTIPLIER if resource_type == agent.specialty
            else C.OFF_SPECIALTY_GATHER_MULTIPLIER)
    if agent.tool_durability > 0:
        mult *= C.TOOL_GATHER_MULTIPLIER
    return mult


def _can_signal(agent: AgentState, node: Node, kind: str, tick: int) -> bool:
    for s in node.signals:
        if s.posted_by == agent.id and s.kind == kind and tick - s.tick < C.SIGNAL_COOLDOWN:
            return False
    return True


def _best_local_score(agent: AgentState, node: Node) -> float:
    if node.resource_type is None or node.quantity <= 0:
        return 0.0
    mult = _gather_yield_multiplier(agent, node.resource_type)
    return marginal_value(agent, node.resource_type) * mult


def _signal_bonus(agent: AgentState, node: Node) -> float:
    bonus = 0.0
    for s in node.signals:
        if s.kind == f"scarce:{ResourceType.FOOD.value}" and agent.held(ResourceType.FOOD) < C.TRADE_MIN_HELD:
            bonus += C.SIGNAL_MOVE_BONUS
        if s.kind == f"scarce:{agent.specialty.value}":
            bonus -= C.SIGNAL_MOVE_BONUS
        if s.kind == f"rich:{agent.specialty.value}":
            bonus += C.SIGNAL_MOVE_BONUS
    return bonus


def _candidates(agent: AgentState, world: World, colocated: list[AgentState],
                 tick: int) -> list[tuple[float, Intent]]:
    candidates: list[tuple[float, Intent]] = []
    node = world.nodes[agent.location]

    # Consume
    if agent.held(ResourceType.FOOD) >= C.CONSUME_FOOD_PER_ACTION:
        score = hunger_pressure(agent) * C.CONSUME_HUNGER_RELIEF
        candidates.append((score, Intent(action="CONSUME", resource=ResourceType.FOOD.value)))

    # Rest — always feasible, the only energy-recovering action
    candidates.append((energy_pressure(agent) * C.REST_ENERGY_GAIN, Intent(action="REST")))

    # Gather
    if node.resource_type is not None and node.quantity > 0:
        mult = _gather_yield_multiplier(agent, node.resource_type)
        score = marginal_value(agent, node.resource_type) * mult
        candidates.append((score, Intent(action="GATHER", target=node.id,
                                          resource=node.resource_type.value)))

    # Craft: 1 ORE + 1 WOOD -> 1 TOOL (refills/equips a fresh tool)
    if agent.held(ResourceType.ORE) >= C.CRAFT_ORE_COST and agent.held(ResourceType.WOOD) >= C.CRAFT_WOOD_COST:
        score = (marginal_value(agent, ResourceType.TOOL)
                 - marginal_value(agent, ResourceType.ORE)
                 - marginal_value(agent, ResourceType.WOOD))
        candidates.append((score, Intent(action="CRAFT")))

    # Trade: mutual benefit is a precondition for even generating the candidate
    if TRADE_ENABLED:
        for other in colocated:
            if other.id == agent.id or not other.alive:
                continue
            for give in RAW_RESOURCES:
                if agent.held(give) < C.TRADE_MIN_HELD:
                    continue
                for want in RAW_RESOURCES:
                    if want == give or other.held(want) < C.TRADE_MIN_HELD:
                        continue
                    my_gain = marginal_value(agent, want) - marginal_value(agent, give)
                    their_gain = marginal_value(other, give) - marginal_value(other, want)
                    if my_gain > 0 and their_gain > 0:
                        candidates.append((my_gain, Intent(
                            action="TRADE", target=other.id,
                            give=give.value, give_amt=C.TRADE_UNIT_AMOUNT,
                            want=want.value, want_amt=C.TRADE_UNIT_AMOUNT,
                        )))

    # Signal (stigmergy): fires when a node crosses a scarcity/abundance threshold
    if node.resource_type is not None and node.max_quantity > 0:
        ratio = node.quantity / node.max_quantity
        kind = None
        if ratio <= C.SIGNAL_LOW_THRESHOLD:
            kind = f"scarce:{node.resource_type.value}"
        elif ratio >= C.SIGNAL_HIGH_THRESHOLD:
            kind = f"rich:{node.resource_type.value}"
        if kind is not None and _can_signal(agent, node, kind, tick):
            candidates.append((C.SIGNAL_VALUE, Intent(action="SIGNAL", target=node.id, resource=kind)))

    # Move: 1-hop lookahead, discounted by edge cost, nudged by signals at the neighbor
    for edge in world.neighbors(agent.location):
        neighbor_id = edge.other(agent.location)
        neighbor = world.nodes[neighbor_id]
        local_best = _best_local_score(agent, neighbor)
        bonus = _signal_bonus(agent, neighbor)
        score = local_best * (C.MOVE_LOOKAHEAD_DISCOUNT ** edge.cost) + bonus
        candidates.append((score, Intent(action="MOVE", target=neighbor_id)))

    return candidates


def choose_action(agent: AgentState, world: World, colocated: list[AgentState],
                   tick: int, rng: random.Random) -> Intent:
    candidates = _candidates(agent, world, colocated, tick)
    if not candidates:
        return Intent(action="REST")
    best_score = None
    best_intent = None
    for score, intent in candidates:
        jittered = score * (1.0 + rng.uniform(-C.JITTER, C.JITTER))
        if best_score is None or jittered > best_score:
            best_score = jittered
            best_intent = intent
    return best_intent
