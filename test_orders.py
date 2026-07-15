"""Standalone headless verification that a standing order actually shifts crowd
behavior, not just exists. Runs the same seed twice - once with an order:wood
signal kept continuously posted at a chosen wood node, once without - and
compares how much wood gets gathered there. Bypasses leads.py entirely on
purpose: this isolates "does the order mechanism work" from "do leads choose
to issue one," which was already verified separately in test_leads.py.

    python test_orders.py --seed 42 --ticks 1500
"""

from __future__ import annotations

import argparse
import random
from collections import defaultdict

from agents import spawn_agents
from tick import run_tick
from world import ResourceType, Signal, generate_world


def run_scenario(seed: int, ticks: int, num_agents: int, num_nodes: int, post_order: bool) -> dict:
    rng = random.Random(seed)
    world = generate_world(num_nodes, rng)
    agents = spawn_agents(num_agents, world, rng)

    wood_node_id = next(nid for nid, n in world.nodes.items() if n.resource_type == ResourceType.WOOD)

    gathered_at_node = 0.0
    attempts_success = 0
    attempts_fail = 0
    for tick in range(1, ticks + 1):
        if post_order:
            node = world.nodes[wood_node_id]
            already_active = any(s.kind == "order:wood" for s in node.signals)
            if not already_active:
                node.signals.append(Signal(kind="order:wood", node_id=wood_node_id,
                                            posted_by="test_orders", tick=tick))

        entries = run_tick(tick, world, agents, rng)
        for e in entries:
            if e.action == "GATHER" and e.target == wood_node_id:
                if e.success:
                    attempts_success += 1
                    amount = next((v for k, v in e.delta.items() if k == "inventory.wood"), 0.0)
                    gathered_at_node += amount
                else:
                    attempts_fail += 1

    return {
        "gathered": gathered_at_node,
        "attempts_success": attempts_success,
        "attempts_fail": attempts_fail,
        "regen_rate": world.nodes[wood_node_id].regen_rate,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--ticks", type=int, default=1500)
    p.add_argument("--agents", type=int, default=40)
    p.add_argument("--nodes", type=int, default=15)
    args = p.parse_args()

    without = run_scenario(args.seed, args.ticks, args.agents, args.nodes, post_order=False)
    with_order = run_scenario(args.seed, args.ticks, args.agents, args.nodes, post_order=True)

    total_without = without["attempts_success"] + without["attempts_fail"]
    total_with = with_order["attempts_success"] + with_order["attempts_fail"]

    print(f"wood node regen rate: {without['regen_rate']:.2f}/tick "
          f"(caps total extractable volume regardless of demand - see LOG.md)")
    print(f"{args.ticks} ticks, seed {args.seed}:")
    print(f"  without order: {total_without} attempts ({without['attempts_success']} succeeded, "
          f"{without['attempts_fail']} failed), {without['gathered']:.1f} wood extracted")
    print(f"  with order:wood: {total_with} attempts ({with_order['attempts_success']} succeeded, "
          f"{with_order['attempts_fail']} failed), {with_order['gathered']:.1f} wood extracted")
    if total_without > 0:
        print(f"  attempt ratio (the real signal of crowd attention shifting): "
              f"{total_with / total_without:.2f}x")


if __name__ == "__main__":
    main()
