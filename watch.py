"""Live view entry point.

    python watch.py --agents 40 --nodes 15 --seed 42
    python watch.py --seed 42 --tps 8
    python watch.py --seed 42 --quit-after 10   (auto-closes after 10s wall time, for smoke tests)

Reuses tick.run_tick, world.generate_world, agents.spawn_agents, and
stats.StatsTracker exactly as Phase 0 left them. Phase 2 adds leads.py's
LLM-driven leads and one player-controlled "hatch" character, both plugged in
purely through tick.run_tick's external_intents override — nothing in the
simulation core needed to know about either concept.
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from typing import Optional

import pygame

import constants as C
import leads
from agents import AgentState, spawn_agents
from decide import Intent, generate_candidates
from layout import compute_layout
from render import draw_agents, draw_hud, draw_legend, draw_player_moves, draw_world
from stats import StatsTracker
from tick import run_tick
from world import RAW_RESOURCES, World, generate_world

SCREEN_SIZE = (1300, 950)
DEFAULT_TPS = 6.0
MIN_TPS = 0.5
MAX_TPS = 60.0
SMOOTHING_RATE = 8.0  # higher = snappier catch-up to the target node position
TUNE_STEP = 0.10       # +/- 10% per keypress
NUM_LEADS = 2

# A curated subset of constants.py worth adjusting live — not all ~35 constants
# change anything you'd notice on screen. Transient only: these edits affect this
# run's `constants` module in memory, never written back to constants.py, so the
# file on disk is never touched by watching a live run.
TUNABLE_CONSTANTS = [
    "SPECIALTY_GATHER_MULTIPLIER",
    "HUNGER_RATE",
    "CONSUME_HUNGER_RELIEF",
    "MAX_USEFUL_HOLDING",
    "TOOL_DURABILITY",
    "SIGNAL_MOVE_BONUS",
    "ORDER_GATHER_MULTIPLIER",
]

NUMBER_KEYS = [
    pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4,
    pygame.K_5, pygame.K_6, pygame.K_7, pygame.K_8, pygame.K_9,
]

ZERO_STEP = 0.5  # a purely multiplicative step can never move a value off exactly zero
                  # (e.g. SIGNAL_MOVE_BONUS starts at 0.0, deliberately, per LOG.md) —
                  # this is the seed value an increase-from-zero jumps to instead


def adjust_tunable(name: str, direction: int) -> float:
    """direction: +1 to increase 10%, -1 to decrease 10%. Preserves int-ness for
    constants like TOOL_DURABILITY so it doesn't quietly turn into a float."""
    current = getattr(C, name)
    if current == 0:
        new_value = ZERO_STEP if direction > 0 else 0.0
    else:
        factor = (1.0 + TUNE_STEP) if direction > 0 else 1.0 / (1.0 + TUNE_STEP)
        new_value = current * factor
    if isinstance(current, int):
        new_value = max(1, round(new_value))
    setattr(C, name, new_value)
    return new_value


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="seam - live view")
    p.add_argument("--agents", type=int, default=C.NUM_AGENTS_DEFAULT)
    p.add_argument("--nodes", type=int, default=C.NUM_NODES_DEFAULT)
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--tps", type=float, default=DEFAULT_TPS, help="ticks per second")
    p.add_argument("--quit-after", type=float, default=None,
                    help="auto-close after N seconds of wall time (for smoke tests)")
    return p.parse_args()


def initial_render_positions(agents, layout: dict[str, tuple[float, float]]) -> dict[str, tuple[float, float]]:
    return {a.id: layout[a.location] for a in agents}


def spawn_player(world: World, rng: random.Random) -> AgentState:
    return AgentState(
        id="player",
        tier="lead",
        location=rng.choice(list(world.nodes.keys())),
        energy=90.0,
        hunger=10.0,
        specialty=RAW_RESOURCES[0],
        goal="player-controlled",
        personality="",
    )


def main() -> int:
    args = parse_args()
    rng = random.Random(args.seed)
    world: World = generate_world(args.nodes, rng)
    crowd = spawn_agents(args.agents, world, rng)
    lead_agents = leads.spawn_leads(NUM_LEADS, world, rng)
    player_agent = spawn_player(world, rng)
    all_agents = crowd + lead_agents + [player_agent]

    layout = compute_layout(world)
    render_pos = initial_render_positions(all_agents, layout)

    stats = StatsTracker(csv_path=None)

    pygame.init()
    pygame.display.set_caption("seam - live view")
    screen = pygame.display.set_mode(SCREEN_SIZE)
    font = pygame.font.SysFont("monospace", 15)
    clock = pygame.time.Clock()

    tick_counter = 0
    paused = False
    ticks_per_second = args.tps
    tick_accumulator = 0.0
    start_time = time.monotonic()
    tunable_index = 0

    possessed = False
    player_pending_intent: Optional[Intent] = None
    player_move_targets: list[str] = []

    running = True
    while running:
        dt_ms = clock.tick(60)
        dt = dt_ms / 1000.0

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE,):
                    running = False
                elif event.key == pygame.K_SPACE:
                    paused = not paused
                elif event.key in (pygame.K_PLUS, pygame.K_EQUALS, pygame.K_KP_PLUS):
                    ticks_per_second = min(MAX_TPS, ticks_per_second * 1.5)
                elif event.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                    ticks_per_second = max(MIN_TPS, ticks_per_second / 1.5)
                elif event.key == pygame.K_TAB:
                    tunable_index = (tunable_index + 1) % len(TUNABLE_CONSTANTS)
                elif event.key == pygame.K_UP:
                    adjust_tunable(TUNABLE_CONSTANTS[tunable_index], +1)
                elif event.key == pygame.K_DOWN:
                    adjust_tunable(TUNABLE_CONSTANTS[tunable_index], -1)
                elif event.key == pygame.K_p:
                    possessed = not possessed
                    player_pending_intent = None
                elif possessed and event.key in NUMBER_KEYS:
                    idx = NUMBER_KEYS.index(event.key)
                    if idx < len(player_move_targets):
                        player_pending_intent = Intent(action="MOVE", target=player_move_targets[idx])
                elif possessed and event.key == pygame.K_g:
                    node = world.nodes[player_agent.location]
                    if node.resource_type is not None:
                        player_pending_intent = Intent(action="GATHER", target=player_agent.location,
                                                        resource=node.resource_type.value)
                elif possessed and event.key == pygame.K_c:
                    player_pending_intent = Intent(action="CONSUME", resource="food")
                elif possessed and event.key == pygame.K_f:
                    player_pending_intent = Intent(action="CRAFT")
                elif possessed and event.key == pygame.K_r:
                    player_pending_intent = Intent(action="REST")
                elif possessed and event.key == pygame.K_t:
                    colocated = [a for a in all_agents if a.alive and a.location == player_agent.location]
                    candidates = generate_candidates(player_agent, world, colocated, tick_counter)
                    trade_candidates = [(s, i) for s, i in candidates if i.action == "TRADE"]
                    if trade_candidates:
                        player_pending_intent = max(trade_candidates, key=lambda pair: pair[0])[1]
                elif possessed and event.key == pygame.K_x:
                    node = world.nodes[player_agent.location]
                    if node.resource_type is not None:
                        player_pending_intent = Intent(action="SIGNAL", target=player_agent.location,
                                                        resource=f"order:{node.resource_type.value}")

        if not paused and any(a.alive for a in all_agents):
            tick_accumulator += dt
            step = 1.0 / ticks_per_second
            while tick_accumulator >= step:
                tick_counter += 1

                external_intents: dict[str, Intent] = {}
                for lead in lead_agents:
                    if lead.alive and tick_counter % leads.LEAD_DECISION_INTERVAL == 0:
                        colocated = [a for a in all_agents if a.alive and a.location == lead.location]
                        intent, _was_llm = leads.decide_lead_action(lead, world, colocated, tick_counter)
                        external_intents[lead.id] = intent
                if possessed and player_agent.alive:
                    external_intents[player_agent.id] = player_pending_intent or Intent(action="REST")
                    player_pending_intent = None

                entries = run_tick(tick_counter, world, all_agents, rng, external_intents=external_intents)
                stats.consume(entries)
                tick_accumulator -= step

        alpha = 1.0 - pow(2.718281828, -SMOOTHING_RATE * dt)
        for agent in all_agents:
            target = layout[agent.location]
            cur = render_pos.get(agent.id, target)
            render_pos[agent.id] = (
                cur[0] + (target[0] - cur[0]) * alpha,
                cur[1] + (target[1] - cur[1]) * alpha,
            )

        screen.fill((18, 18, 24))
        draw_world(screen, world, layout, SCREEN_SIZE)
        draw_agents(screen, all_agents, render_pos, SCREEN_SIZE,
                    player_agent_id=player_agent.id, possessed=possessed)
        if possessed and player_agent.alive:
            player_move_targets = draw_player_moves(screen, font, world, player_agent.location, layout, SCREEN_SIZE)
        else:
            player_move_targets = []
        draw_legend(screen, font, SCREEN_SIZE)
        population = sum(1 for a in all_agents if a.alive)
        tunable_name = TUNABLE_CONSTANTS[tunable_index]
        draw_hud(
            screen, font,
            tick=tick_counter, population=population, total=len(all_agents),
            cumulative_trades=stats.cumulative_trades, cumulative_crafts=stats.cumulative_crafts,
            specialization_idx=stats.specialization_index(all_agents),
            paused=paused, ticks_per_second=ticks_per_second,
            tunable_name=tunable_name, tunable_value=getattr(C, tunable_name),
            possessed=possessed,
        )
        pygame.display.flip()

        if args.quit_after is not None and (time.monotonic() - start_time) >= args.quit_after:
            running = False

    pygame.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
