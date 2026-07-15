"""Per-action resolution: mutate world/agent state, produce a TickLogEntry.

Trade is the one action that involves two agents. It resolves as a single-shot
offer/accept, not a negotiation: the initiator's candidate was already checked
at decide time to be mutually beneficial using the partner's observed
inventory; at resolution time we re-check against the partner's *current*
state (it may have changed since decide) and, if it's still not a loss for
the partner, execute the swap immediately.
"""

from __future__ import annotations

import random
from typing import Optional

import constants as C
from agents import AgentState
from decide import Intent, marginal_value
from log import TickLogEntry, diff
from world import ResourceType, Signal, World


def _entry(tick: int, agent: AgentState, action: str, target: Optional[str],
           success: bool, before: dict, after: dict) -> TickLogEntry:
    return TickLogEntry(
        tick=tick, agent_id=agent.id, tier=agent.tier,
        state_before=before, action=action, target=target,
        success=success, state_after=after, delta=diff(before, after),
    )


def resolve_move(agent: AgentState, world: World, intent: Intent, tick: int) -> TickLogEntry:
    before = agent.snapshot()
    edge = next((e for e in world.neighbors(agent.location) if e.other(agent.location) == intent.target), None)
    success = edge is not None
    if success:
        agent.location = intent.target
        agent.energy = max(0.0, agent.energy - edge.cost * C.MOVE_ENERGY_COST_FACTOR)
    after = agent.snapshot()
    return _entry(tick, agent, "MOVE", intent.target, success, before, after)


def resolve_gather(agent: AgentState, world: World, intent: Intent, tick: int) -> TickLogEntry:
    before = agent.snapshot()
    node = world.nodes[agent.location]
    resource = ResourceType(intent.resource)
    success = node.id == intent.target and node.resource_type == resource and node.quantity > 0
    if success:
        mult = (C.SPECIALTY_GATHER_MULTIPLIER if resource == agent.specialty
                else C.OFF_SPECIALTY_GATHER_MULTIPLIER)
        if agent.tool_durability > 0:
            mult *= C.TOOL_GATHER_MULTIPLIER
            agent.tool_durability -= 1
        amount = min(node.quantity, C.GATHER_AMOUNT * mult)
        node.quantity -= amount
        agent.add(resource, amount)
        agent.energy = max(0.0, agent.energy - C.GATHER_ENERGY_COST)
    after = agent.snapshot()
    return _entry(tick, agent, "GATHER", intent.target, success, before, after)


def resolve_craft(agent: AgentState, intent: Intent, tick: int) -> TickLogEntry:
    before = agent.snapshot()
    success = (agent.held(ResourceType.ORE) >= C.CRAFT_ORE_COST
               and agent.held(ResourceType.WOOD) >= C.CRAFT_WOOD_COST)
    if success:
        agent.remove(ResourceType.ORE, C.CRAFT_ORE_COST)
        agent.remove(ResourceType.WOOD, C.CRAFT_WOOD_COST)
        agent.tool_durability = C.TOOL_DURABILITY
    after = agent.snapshot()
    return _entry(tick, agent, "CRAFT", None, success, before, after)


def resolve_consume(agent: AgentState, intent: Intent, tick: int) -> TickLogEntry:
    before = agent.snapshot()
    success = agent.held(ResourceType.FOOD) >= C.CONSUME_FOOD_PER_ACTION
    if success:
        agent.remove(ResourceType.FOOD, C.CONSUME_FOOD_PER_ACTION)
        agent.hunger = max(0.0, agent.hunger - C.CONSUME_HUNGER_RELIEF)
    after = agent.snapshot()
    return _entry(tick, agent, "CONSUME", None, success, before, after)


def resolve_rest(agent: AgentState, intent: Intent, tick: int) -> TickLogEntry:
    before = agent.snapshot()
    agent.energy = min(100.0, agent.energy + C.REST_ENERGY_GAIN)
    after = agent.snapshot()
    return _entry(tick, agent, "REST", None, True, before, after)


def resolve_signal(agent: AgentState, world: World, intent: Intent, tick: int) -> TickLogEntry:
    before = agent.snapshot()
    node = world.nodes[agent.location]
    node.signals.append(Signal(kind=intent.resource, node_id=node.id, posted_by=agent.id, tick=tick))
    after = agent.snapshot()
    return _entry(tick, agent, "SIGNAL", intent.resource, True, before, after)


def _trade_feasible(agent: AgentState, partner: Optional[AgentState], intent: Intent) -> bool:
    if partner is None or not partner.alive or partner.location != agent.location:
        return False
    if agent.held(ResourceType(intent.give)) < intent.give_amt:
        return False
    if partner.held(ResourceType(intent.want)) < intent.want_amt:
        return False
    # partner must not lose by accepting, evaluated fresh against their current state
    partner_receives_value = marginal_value(partner, ResourceType(intent.give))
    partner_gives_up_value = marginal_value(partner, ResourceType(intent.want))
    return partner_receives_value >= partner_gives_up_value


def _execute_swap(agent: AgentState, partner: AgentState, intent: Intent) -> None:
    agent.remove(ResourceType(intent.give), intent.give_amt)
    agent.add(ResourceType(intent.want), intent.want_amt)
    partner.remove(ResourceType(intent.want), intent.want_amt)
    partner.add(ResourceType(intent.give), intent.give_amt)


def resolve_trade_phase(agents_by_id: dict[str, AgentState], intents: dict[str, Intent],
                         tick: int, rng: random.Random) -> list[TickLogEntry]:
    """Processes all TRADE-intent agents in shuffled order (no first-mover bias).

    If a swap succeeds, both sides get a log entry from this single resolution.
    If the partner's own chosen intent was *also* TRADE, it's marked settled so
    the outer loop doesn't execute it again as a second, separate swap.
    """
    entries: list[TickLogEntry] = []
    initiators = [aid for aid, intent in intents.items()
                  if intent.action == "TRADE" and agents_by_id[aid].alive]
    rng.shuffle(initiators)
    settled: set[str] = set()

    for aid in initiators:
        if aid in settled:
            continue
        agent = agents_by_id[aid]
        intent = intents[aid]
        agent_before = agent.snapshot()
        partner = agents_by_id.get(intent.target)
        success = _trade_feasible(agent, partner, intent)
        partner_before = partner.snapshot() if partner is not None else None

        if success:
            _execute_swap(agent, partner, intent)

        agent_after = agent.snapshot()
        entries.append(_entry(tick, agent, "TRADE", intent.target, success, agent_before, agent_after))

        if success:
            settled.add(agent.id)
            partner_after = partner.snapshot()
            entries.append(_entry(tick, partner, "TRADE", agent.id, True, partner_before, partner_after))
            if partner.id in intents and intents[partner.id].action == "TRADE":
                settled.add(partner.id)

    return entries
