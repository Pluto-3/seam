"""Live view entry point.

    python watch.py --agents 40 --nodes 15 --seed 42
    python watch.py --seed 42 --tps 8
    python watch.py --seed 42 --quit-after 10   (auto-closes after 10s wall time, for smoke tests)

Reuses tick.run_tick, world.generate_world, agents.spawn_agents, and
stats.StatsTracker exactly as Phase 0 left them — this file only adds a
pygame front end on top, nothing in the simulation core changes.
"""

from __future__ import annotations

import argparse
import random
import sys
import time

import pygame

import constants as C
from agents import spawn_agents
from layout import compute_layout
from render import draw_agents, draw_hud, draw_legend, draw_world
from stats import StatsTracker
from tick import run_tick
from world import World, generate_world

SCREEN_SIZE = (1300, 950)
DEFAULT_TPS = 6.0
MIN_TPS = 0.5
MAX_TPS = 60.0
SMOOTHING_RATE = 8.0  # higher = snappier catch-up to the target node position
TUNE_STEP = 0.10       # +/- 10% per keypress

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
    p = argparse.ArgumentParser(description="seam - Phase 1 live view")
    p.add_argument("--agents", type=int, default=C.NUM_AGENTS_DEFAULT)
    p.add_argument("--nodes", type=int, default=C.NUM_NODES_DEFAULT)
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--tps", type=float, default=DEFAULT_TPS, help="ticks per second")
    p.add_argument("--quit-after", type=float, default=None,
                    help="auto-close after N seconds of wall time (for smoke tests)")
    return p.parse_args()


def initial_render_positions(agents, layout: dict[str, tuple[float, float]]) -> dict[str, tuple[float, float]]:
    return {a.id: layout[a.location] for a in agents}


def main() -> int:
    args = parse_args()
    rng = random.Random(args.seed)
    world: World = generate_world(args.nodes, rng)
    agents = spawn_agents(args.agents, world, rng)
    layout = compute_layout(world)
    render_pos = initial_render_positions(agents, layout)

    stats = StatsTracker(csv_path=None)

    pygame.init()
    pygame.display.set_caption("seam - Phase 1 live view")
    screen = pygame.display.set_mode(SCREEN_SIZE)
    font = pygame.font.SysFont("monospace", 15)
    clock = pygame.time.Clock()

    tick_counter = 0
    paused = False
    ticks_per_second = args.tps
    tick_accumulator = 0.0
    start_time = time.monotonic()
    tunable_index = 0

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

        if not paused and any(a.alive for a in agents):
            tick_accumulator += dt
            step = 1.0 / ticks_per_second
            while tick_accumulator >= step:
                tick_counter += 1
                entries = run_tick(tick_counter, world, agents, rng)
                stats.consume(entries)
                tick_accumulator -= step

        alpha = 1.0 - pow(2.718281828, -SMOOTHING_RATE * dt)
        for agent in agents:
            target = layout[agent.location]
            cur = render_pos.get(agent.id, target)
            render_pos[agent.id] = (
                cur[0] + (target[0] - cur[0]) * alpha,
                cur[1] + (target[1] - cur[1]) * alpha,
            )

        screen.fill((18, 18, 24))
        draw_world(screen, world, layout, SCREEN_SIZE)
        draw_agents(screen, agents, render_pos, SCREEN_SIZE)
        draw_legend(screen, font, SCREEN_SIZE)
        population = sum(1 for a in agents if a.alive)
        tunable_name = TUNABLE_CONSTANTS[tunable_index]
        draw_hud(
            screen, font,
            tick=tick_counter, population=population, total=len(agents),
            cumulative_trades=stats.cumulative_trades, cumulative_crafts=stats.cumulative_crafts,
            specialization_idx=stats.specialization_index(agents),
            paused=paused, ticks_per_second=ticks_per_second,
            tunable_name=tunable_name, tunable_value=getattr(C, tunable_name),
        )
        pygame.display.flip()

        if args.quit_after is not None and (time.monotonic() - start_time) >= args.quit_after:
            running = False

    pygame.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
