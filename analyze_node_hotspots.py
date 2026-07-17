"""Angle 6 of ANALYSIS.md: node-level spatial hotspots.

Every prior contention analysis (Phase 3/4, analyze_cross_society.py) has
been at the *society* level. This looks at the raw graph instead - across
all nodes, independent of which society calls a node home turf: which
nodes are permanent hotspots, which are dead zones never visited, and
which societies actually mix at each one.

Usage: python3 analyze_node_hotspots.py run.jsonl [run2.jsonl ...]
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path


def analyze(path: Path) -> None:
    print(f"\n{'=' * 70}\n{path.name}\n{'=' * 70}")

    presence: dict[str, int] = defaultdict(int)          # node -> action-count that happened there
    deaths: dict[str, int] = defaultdict(int)             # node -> death count
    societies_seen: dict[str, set] = defaultdict(set)     # node -> distinct societies ever present

    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            loc = e.get("state_after", {}).get("location") or e.get("state_before", {}).get("location")
            if not loc:
                continue
            presence[loc] += 1
            if e["action"] == "DEATH":
                deaths[loc] += 1
            if e.get("society"):
                societies_seen[loc].add(e["society"])

    all_nodes = sorted(presence.keys())
    total_actions = sum(presence.values())
    print(f"{len(all_nodes)} distinct nodes visited, {total_actions} total logged actions")

    ranked = sorted(all_nodes, key=lambda n: -presence[n])
    print("\nnodes ranked by total activity (busiest first):")
    for n in ranked:
        pct = presence[n] / total_actions * 100
        soc_count = len(societies_seen[n])
        print(f"  {n}: {presence[n]:>7} actions ({pct:4.1f}%), {soc_count} distinct societies ever present, {deaths[n]} deaths here")

    cold = [n for n in ranked if presence[n] < total_actions * 0.005]
    print(f"\n'dead zone' nodes (<0.5% of all activity): {cold if cold else '(none - every node saw meaningful use)'}")

    if deaths:
        death_nodes = sorted(deaths.items(), key=lambda kv: -kv[1])
        print(f"\ndeaths by node: {death_nodes}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python3 analyze_node_hotspots.py run1.jsonl [run2.jsonl ...]")
        sys.exit(1)
    for p in sys.argv[1:]:
        analyze(Path(p))
