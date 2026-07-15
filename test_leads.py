"""Standalone headless verification for leads.py - not part of any test framework,
same spirit as Phase 0's early hand-traced runs. Spawns a small crowd plus a
couple of LLM-driven leads, runs a few hundred ticks, and prints every
LLM-driven decision (which candidates were on offer, what was chosen, whether
it was a real LLM choice or the argmax fallback) so it can be read by hand.

    python test_leads.py --seed 42 --ticks 400
    python test_leads.py --seed 42 --ticks 100 --break-model   (forces every lead
        decision through the fallback path, to prove it's actually exercised)
"""

from __future__ import annotations

import argparse
import random

import leads
from agents import spawn_agents
from tick import run_tick
from world import generate_world


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--ticks", type=int, default=400)
    p.add_argument("--agents", type=int, default=20)
    p.add_argument("--nodes", type=int, default=12)
    p.add_argument("--num-leads", type=int, default=2)
    p.add_argument("--break-model", action="store_true",
                    help="use a nonexistent model name to force the fallback path")
    args = p.parse_args()

    model = "definitely-not-a-real-model-xyz" if args.break_model else leads.DEFAULT_MODEL

    rng = random.Random(args.seed)
    world = generate_world(args.nodes, rng)
    crowd = spawn_agents(args.agents, world, rng)
    lead_agents = leads.spawn_leads(args.num_leads, world, rng)
    all_agents = crowd + lead_agents
    agents_by_id = {a.id: a for a in all_agents}

    llm_choices = 0
    fallback_choices = 0

    for tick in range(1, args.ticks + 1):
        external_intents = {}
        for lead in lead_agents:
            if not lead.alive:
                continue
            if tick % leads.LEAD_DECISION_INTERVAL != 0:
                continue
            colocated = [a for a in all_agents if a.alive and a.location == lead.location]
            node_occupancy = {}
            for a in all_agents:
                if a.alive:
                    node_occupancy[a.location] = node_occupancy.get(a.location, 0) + 1
            intent, was_llm = leads.decide_lead_action(lead, world, colocated, tick, node_occupancy, model=model)
            external_intents[lead.id] = intent
            if was_llm:
                llm_choices += 1
            else:
                fallback_choices += 1
            tag = "LLM" if was_llm else "fallback"
            print(f"tick {tick:4d} {lead.id} [{tag}] goal='{lead.goal}' "
                  f"state(e={lead.energy:.0f} h={lead.hunger:.0f} inv={dict(lead.inventory)}) "
                  f"-> {intent.action} target={intent.target}")

        run_tick(tick, world, all_agents, rng, external_intents=external_intents)

    print()
    print(f"total lead decisions: {llm_choices + fallback_choices}   "
          f"llm={llm_choices}   fallback={fallback_choices}")
    for lead in lead_agents:
        print(f"{lead.id} final: alive={lead.alive} energy={lead.energy:.1f} "
              f"hunger={lead.hunger:.1f} inv={dict(lead.inventory)}")


if __name__ == "__main__":
    main()
