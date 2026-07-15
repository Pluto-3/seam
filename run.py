"""Entry point.

    python run.py --ticks 2000 --agents 40 --nodes 15 --seed 42
    python run.py --selftest
    python run.py --no-trade --seed 42   (negative control)
"""

from __future__ import annotations

import argparse
import os
import random
import sys

import constants as C
import decide
from agents import spawn_agents
from log import JsonlWriter
from stats import StatsTracker
from tick import run_tick
from world import generate_world


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="seam - Phase 0 headless mechanic test")
    p.add_argument("--ticks", type=int, default=C.TICKS_DEFAULT)
    p.add_argument("--agents", type=int, default=C.NUM_AGENTS_DEFAULT)
    p.add_argument("--nodes", type=int, default=C.NUM_NODES_DEFAULT)
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--stats-every", type=int, default=C.STATS_EVERY_DEFAULT)
    p.add_argument("--log-path", type=str, default="logs/run.jsonl")
    p.add_argument("--stats-csv", type=str, default="logs/stats.csv")
    p.add_argument("--no-trade", action="store_true", help="negative control: disable trade")
    p.add_argument("--selftest", action="store_true", help="run structural sanity checks and exit")
    return p.parse_args()


def selftest(args: argparse.Namespace) -> int:
    rng = random.Random(args.seed if args.seed is not None else 0)
    world = generate_world(args.nodes, rng)
    ok = True

    if not world.is_connected():
        print("FAIL: generated world is not fully connected")
        ok = False
    else:
        print("OK: world is fully connected")

    agents = spawn_agents(args.agents, world, rng)
    for t in range(1, 51):
        run_tick(t, world, agents, rng)
        for a in agents:
            if not (-1e-6 <= a.energy <= 100 + 1e-6):
                print(f"FAIL: agent {a.id} energy out of range at tick {t}: {a.energy}")
                ok = False
            if not (-1e-6 <= a.hunger <= 100 + 1e-6):
                print(f"FAIL: agent {a.id} hunger out of range at tick {t}: {a.hunger}")
                ok = False
            for res, amt in a.inventory.items():
                if amt < -1e-6:
                    print(f"FAIL: agent {a.id} negative inventory {res}={amt} at tick {t}")
                    ok = False

    if ok:
        print("OK: 50-tick run stayed within valid state bounds")
    print("SELFTEST PASSED" if ok else "SELFTEST FAILED")
    return 0 if ok else 1


def main() -> int:
    args = parse_args()

    if args.selftest:
        return selftest(args)

    if args.no_trade:
        decide.TRADE_ENABLED = False

    rng = random.Random(args.seed)
    world = generate_world(args.nodes, rng)
    agents = spawn_agents(args.agents, world, rng)

    log_dir = os.path.dirname(args.log_path) or "."
    os.makedirs(log_dir, exist_ok=True)
    csv_dir = os.path.dirname(args.stats_csv) or "."
    os.makedirs(csv_dir, exist_ok=True)

    log_writer = JsonlWriter(args.log_path)
    stats = StatsTracker(args.stats_csv)

    print(f"seam Phase 0 - agents={args.agents} nodes={args.nodes} ticks={args.ticks} "
          f"seed={args.seed} trade={'OFF' if args.no_trade else 'on'}")
    print()

    try:
        for t in range(1, args.ticks + 1):
            entries = run_tick(t, world, agents, rng)
            for entry in entries:
                log_writer.write(entry)
            stats.consume(entries)
            if t % args.stats_every == 0 or t == args.ticks:
                stats.snapshot(t, agents, world)
    finally:
        log_writer.close()
        stats.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
