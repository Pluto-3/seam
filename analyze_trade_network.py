"""Angle 2 of ANALYSIS.md: trade network topology.

Builds the actual agent-to-agent trade graph (never done before this
project - every prior analysis only measured aggregate cross-society %)
and asks the question that motivated it: does an agent's *position* in the
network predict its outcome more than its own trading skill does? Research
on real economic networks (see ANALYSIS.md's sources) found random/small-
world trade networks produce meritocratic outcomes, scale-free ones produce
topocratic ones - position matters more than merit. Tests that distinction
directly against this project's own society3 finding (no lead, did just as
well as the best led society) - is that about position, not leadership?

One real pass over the log builds: the weighted trade graph, each agent's
own trade success rate (a proxy for "skill"), final wealth, and survival -
then checks which of {network centrality, own trade success rate} actually
correlates with wealth/survival.

Usage: python3 analyze_trade_network.py run.jsonl [run2.jsonl ...]
Requires numpy/networkx/scipy (venv only, see requirements.txt).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import networkx as nx
import numpy as np
from scipy import stats


def analyze(path: Path) -> None:
    print(f"\n{'=' * 70}\n{path.name}\n{'=' * 70}")

    G = nx.Graph()
    trade_attempts: dict[str, int] = {}
    trade_successes: dict[str, int] = {}
    last_state: dict[str, dict] = {}
    society_of: dict[str, str] = {}

    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            e = json.loads(line)
            aid = e["agent_id"]
            last_state[aid] = e  # overwritten each time - ends up as the last entry seen
            if e.get("society"):
                society_of[aid] = e["society"]

            if e["action"] != "TRADE":
                continue
            trade_attempts[aid] = trade_attempts.get(aid, 0) + 1
            if e["success"] and e.get("target"):
                trade_successes[aid] = trade_successes.get(aid, 0) + 1
                target = e["target"]
                if G.has_edge(aid, target):
                    G[aid][target]["weight"] += 1
                else:
                    G.add_edge(aid, target, weight=1)

    print(f"trade graph: {G.number_of_nodes()} agents, {G.number_of_edges()} distinct trade relationships")
    if G.number_of_edges() == 0:
        print("(no successful trades - nothing to analyze)")
        return

    # --- centrality ---
    degree_cent = nx.degree_centrality(G)
    # betweenness on the full graph can be slow; fine at this scale (tens of nodes)
    betweenness_cent = nx.betweenness_centrality(G, weight=None)

    top_degree = sorted(degree_cent.items(), key=lambda kv: -kv[1])[:5]
    print("\ntop 5 by degree centrality (most distinct trade partners):")
    for aid, c in top_degree:
        print(f"  {aid}: {c:.3f} ({G.degree(aid)} partners, society={society_of.get(aid, '?')})")

    top_between = sorted(betweenness_cent.items(), key=lambda kv: -kv[1])[:5]
    print("\ntop 5 by betweenness centrality (most likely to bridge two otherwise-separate trade clusters):")
    for aid, c in top_between:
        print(f"  {aid}: {c:.4f} (society={society_of.get(aid, '?')})")

    # --- community detection vs society boundaries ---
    communities = list(nx.algorithms.community.greedy_modularity_communities(G, weight="weight"))
    print(f"\n{len(communities)} trade communities detected (modularity-based, ignoring society labels entirely)")
    for i, comm in enumerate(communities):
        socs = [society_of.get(a) for a in comm if society_of.get(a)]
        if not socs:
            continue
        dominant = max(set(socs), key=socs.count)
        purity = socs.count(dominant) / len(socs)
        print(f"  community {i}: {len(comm)} agents, dominant society={dominant} (purity {purity:.0%})")

    # --- meritocratic vs topocratic: does position or own skill predict outcome? ---
    agents = [a for a in G.nodes() if a in last_state]
    wealth = {}
    survived = {}
    skill = {}
    for a in agents:
        inv = last_state[a].get("state_after", {}).get("inventory", {})
        wealth[a] = sum(v for v in inv.values() if isinstance(v, (int, float)))
        survived[a] = 1 if last_state[a].get("state_after", {}).get("alive", True) else 0
        attempts = trade_attempts.get(a, 0)
        skill[a] = trade_successes.get(a, 0) / attempts if attempts > 0 else 0.0

    xs_wealth = np.array([wealth[a] for a in agents])
    xs_survived = np.array([survived[a] for a in agents])
    xs_centrality = np.array([degree_cent[a] for a in agents])
    xs_skill = np.array([skill[a] for a in agents])

    def safe_corr(x, y, label):
        if np.std(x) == 0 or np.std(y) == 0:
            print(f"  {label}: undefined (no variance)")
            return
        r, p = stats.spearmanr(x, y)
        print(f"  {label}: rho={r:+.3f} (p={p:.3g})")

    print("\nmeritocratic (own trade skill) vs topocratic (network position) - which predicts outcome?")
    print(" wealth vs:")
    safe_corr(xs_centrality, xs_wealth, "  network centrality")
    safe_corr(xs_skill, xs_wealth, "  own trade success rate")
    print(" survival vs:")
    safe_corr(xs_centrality, xs_survived, "  network centrality")
    safe_corr(xs_skill, xs_survived, "  own trade success rate")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python3 analyze_trade_network.py run1.jsonl [run2.jsonl ...]")
        sys.exit(1)
    for p in sys.argv[1:]:
        analyze(Path(p))
