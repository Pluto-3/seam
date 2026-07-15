"""The tick loop: regen -> metabolism -> decide -> resolve -> log.

Authoritative resolve order: MOVE, GATHER, CRAFT, CONSUME, TRADE, REST, SIGNAL.
Trade resolves after Move so an agent that just walked to a partner can still
trade that tick. Rest is the only energy-recovering action, resolved after
Trade so Move/Gather's energy costs are real opportunity costs, not free.
"""

from __future__ import annotations

import random
from collections import defaultdict

import actions as A
import constants as C
from agents import AgentState
from decide import Intent, choose_action
from log import TickLogEntry, diff
from world import World

_RESOLVE_ORDER = ("MOVE", "GATHER", "CRAFT", "CONSUME")
_LATE_ORDER = ("REST", "SIGNAL")


def _death_entry(tick: int, agent: AgentState) -> TickLogEntry:
    before = agent.snapshot()
    agent.alive = False
    after = agent.snapshot()
    return TickLogEntry(
        tick=tick, agent_id=agent.id, tier=agent.tier,
        state_before=before, action="DEATH", target=None,
        success=True, state_after=after, delta=diff(before, after),
    )


def _is_dead(agent: AgentState) -> bool:
    return agent.hunger >= C.DEATH_HUNGER_MAX or agent.energy <= C.DEATH_ENERGY_MIN


def run_tick(tick: int, world: World, agents: list[AgentState], rng: random.Random) -> list[TickLogEntry]:
    entries: list[TickLogEntry] = []
    agents_by_id = {a.id: a for a in agents}

    # 1. housekeeping
    world.regen()
    world.prune_signals(tick)

    # 2. metabolism + death check pass 1
    for agent in agents:
        if not agent.alive:
            continue
        agent.hunger = min(100.0, agent.hunger + C.HUNGER_RATE)
        agent.energy = max(0.0, agent.energy - C.ENERGY_DECAY_RATE)
        if _is_dead(agent):
            entries.append(_death_entry(tick, agent))

    # 3. decide, from one consistent post-metabolism snapshot
    by_location: dict[str, list[AgentState]] = defaultdict(list)
    for agent in agents:
        if agent.alive:
            by_location[agent.location].append(agent)

    intents: dict[str, Intent] = {}
    for agent in agents:
        if not agent.alive:
            continue
        colocated = by_location[agent.location]
        intents[agent.id] = choose_action(agent, world, colocated, tick, rng)

    # 4. resolve in fixed phase order, each phase in shuffled agent order
    for phase in _RESOLVE_ORDER:
        actors = [a for a in agents if a.alive and intents.get(a.id) and intents[a.id].action == phase]
        rng.shuffle(actors)
        for agent in actors:
            intent = intents[agent.id]
            if phase == "MOVE":
                entries.append(A.resolve_move(agent, world, intent, tick))
            elif phase == "GATHER":
                entries.append(A.resolve_gather(agent, world, intent, tick))
            elif phase == "CRAFT":
                entries.append(A.resolve_craft(agent, intent, tick))
            elif phase == "CONSUME":
                entries.append(A.resolve_consume(agent, intent, tick))

    entries.extend(A.resolve_trade_phase(agents_by_id, intents, tick, rng))

    for phase in _LATE_ORDER:
        actors = [a for a in agents if a.alive and intents.get(a.id) and intents[a.id].action == phase]
        rng.shuffle(actors)
        for agent in actors:
            intent = intents[agent.id]
            if phase == "REST":
                entries.append(A.resolve_rest(agent, intent, tick))
            elif phase == "SIGNAL":
                entries.append(A.resolve_signal(agent, world, intent, tick))

    # 5. death check pass 2 — move/gather energy costs can be the actual tipping point
    for agent in agents:
        if agent.alive and _is_dead(agent):
            entries.append(_death_entry(tick, agent))

    return entries
