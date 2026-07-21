"""Trade network reconstruction from a sidecar decisions.jsonl log, for runs
with no raw tick-level JSONL (analyze_trade_network.py needs that; this run
only has --stats-csv/--society-stats-csv plus the sidecar's own decision
log). Real scope limits, stated plainly rather than glossed over:

  - Only LEAD-initiated trades are visible here. Crowd agents aren't
    LLM-driven, so their trades never appear in this log at all - this is a
    lead-centric subgraph of the real trade network, not the whole thing.
  - This is what a lead *chose* (chosen_description), not a confirmed
    successful resolution - the decision log has no success/failure field
    (that lives server-side, in the raw tick log this run doesn't have).
    Treat edges as "attempted/intended trades," not "trades that happened."

Usage: python3 analyze_trade_network_sidecar.py sidecar.jsonl
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

import networkx as nx

TRADE_RE = re.compile(r"TRADE -> (\S+) \(give (\d+) (\w+), get (\d+) (\w+)\)")


def load_trades(path: Path) -> list[dict]:
    trades = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("kind") != "decision" or e.get("chosen_action") != "TRADE":
                continue
            m = TRADE_RE.match(e.get("chosen_description", ""))
            if not m:
                continue
            partner, give_amt, give_res, get_amt, get_res = m.groups()
            trades.append({
                "initiator": e["lead_id"], "partner": partner,
                "give_amt": int(give_amt), "give_res": give_res,
                "get_amt": int(get_amt), "get_res": get_res,
                "ts": e["ts"],
            })
    return trades


def analyze(path: Path) -> None:
    trades = load_trades(path)
    print(f"\n{'=' * 70}\n{path.name}\n{'=' * 70}")
    print(f"{len(trades)} real lead-initiated TRADE decisions parsed")

    initiators = Counter(t["initiator"] for t in trades)
    print(f"\nby initiator: {dict(initiators)}")

    partner_tier = Counter("lead/hatch" if t["partner"].startswith(("lead", "hatch")) else "crowd" for t in trades)
    print(f"by partner tier: {dict(partner_tier)}")

    G = nx.DiGraph()
    for t in trades:
        w = G.get_edge_data(t["initiator"], t["partner"], default={"weight": 0})["weight"]
        G.add_edge(t["initiator"], t["partner"], weight=w + 1)

    print(f"\ngraph: {G.number_of_nodes()} real distinct agents touched, {G.number_of_edges()} distinct initiator->partner pairs")

    # Top partners per lead - who each lead actually trades with most, not
    # just aggregate volume.
    for lead in sorted(initiators):
        edges = [(v, d["weight"]) for u, v, d in G.out_edges(lead, data=True)]
        edges.sort(key=lambda x: -x[1])
        top = edges[:5]
        print(f"\n{lead}'s top trade partners (attempts): {top}")

    # Centrality on the undirected projection - who's structurally most
    # "connected" across the whole reconstructed network, not just by raw
    # volume with one partner.
    UG = G.to_undirected()
    centrality = nx.degree_centrality(UG)
    top_central = sorted(centrality.items(), key=lambda x: -x[1])[:8]
    print(f"\ntop-8 by degree centrality (distinct trade partners, not volume): {top_central}")

    # Resource flow: net direction per resource type, from the initiator's
    # own perspective (give = leaving the initiator, get = arriving).
    resource_flow: Counter = Counter()
    for t in trades:
        resource_flow[t["give_res"]] -= t["give_amt"]
        resource_flow[t["get_res"]] += t["get_amt"]
    print(f"\nnet resource flow *into* lead-initiators across all attempts: {dict(resource_flow)}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python3 analyze_trade_network_sidecar.py sidecar.jsonl")
        sys.exit(1)
    analyze(Path(sys.argv[1]))
