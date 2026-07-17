"""v3 Phase 3: how much of what happens in a run is cross-society?

Formalizes the ad hoc counting done by hand for DESIGN-V3.md's Phase 0
proof (22,894/36,201 cross-society trades in one run) into a script that
can be rerun against any log, so Phase 3's "does implicit rivalry hold up
across varied conditions" question can be checked across several runs
instead of trusting one config. Reuses analyze_congestion_fix.py's
gather-fail-rate formula directly; needs only the raw --full-log JSONL,
same "just read the log" posture as every other analyze_*.py script here.

Society membership is reconstructed, not assumed from id ranges: every
roster/hatch/lead agent gets relocated to (or spawned at) its society's
home node at tick 0, so grouping agents by their earliest-observed
state_before.location recovers the same society clusters regardless of
seed, node count, or roster size - the exact method already validated by
hand for the Phase 0 numbers above.

Usage: python3 analyze_cross_society.py run1.jsonl run2.jsonl ...
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path


def load_entries(path: Path) -> list[dict]:
    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def society_clusters(entries: list[dict]) -> dict[str, str]:
    """agent_id -> cluster label (its earliest-observed home node).

    Only rostered agents (crowd relocated at spawn, plus their hatch/lead)
    actually belong to a society - free-roaming crowd agents spawn at
    random locations and belong to none. A size-based cutoff (real homes
    are bigger clusters than random collisions) turned out not to be
    robust: with a large free-roaming pool (e.g. --societies 1, where 32
    of 40 crowd agents are unrostered), random collisions at the same
    spawn node occasionally get big enough to cross a relative threshold
    and get misread as a phantom extra society - caught by testing against
    an actual isolated-baseline run, not assumed safe.

    A hatch or lead agent's location is never random - hatch{i}/lead{i}
    are deliberately spawned at their society's home node, always,
    regardless of roster size or free-roaming population. So real home
    nodes are identified by presence of a hatch/lead id there, not by
    cluster size - a random crowd-only collision can never include one,
    since hatches/leads aren't part of spawn_agents' random pool at all.

    Superseded, when present, by ground-truth: logs written after the
    serve_main.rs society-tagging change carry a real "society" field on
    every entry (via the same society_of() the sim itself uses) - no
    clustering or guessing needed at all. Older logs (e.g. everything from
    Phase 3) don't have it, so the heuristic below stays as a fallback.
    """
    ground_truth = {e["agent_id"]: e["society"] for e in entries if e.get("society")}
    if ground_truth:
        return ground_truth

    first_loc: dict[str, str] = {}
    for e in entries:
        aid = e["agent_id"]
        if aid in first_loc:
            continue
        loc = e.get("state_before", {}).get("location")
        if loc:
            first_loc[aid] = loc

    real_homes = {
        loc for aid, loc in first_loc.items()
        if aid.startswith("hatch") or aid.startswith("lead")
    }

    return {aid: loc for aid, loc in first_loc.items() if loc in real_homes}


def cross_society_trades(entries: list[dict], cluster: dict[str, str]) -> tuple[int, int, int, int]:
    """(total attempted, total successful, cross-society attempted, cross-society successful)."""
    total, total_ok, cross, cross_ok = 0, 0, 0, 0
    for e in entries:
        if e["action"] != "TRADE" or not e.get("target"):
            continue
        total += 1
        if e["success"]:
            total_ok += 1
        c1, c2 = cluster.get(e["agent_id"]), cluster.get(e["target"])
        if c1 and c2 and c1 != c2:
            cross += 1
            if e["success"]:
                cross_ok += 1
    return total, total_ok, cross, cross_ok


def cross_society_contention(entries: list[dict], cluster: dict[str, str]) -> tuple[int, int]:
    """(total tick x node occupancy groups, groups with 2+ distinct societies present)."""
    by_tick_node: dict[tuple[int, str], set[str]] = defaultdict(set)
    for e in entries:
        loc = e.get("state_after", {}).get("location") or e.get("state_before", {}).get("location")
        c = cluster.get(e["agent_id"])
        if loc and c:
            by_tick_node[(e["tick"], loc)].add(c)
    total_groups = len(by_tick_node)
    contested = sum(1 for socs in by_tick_node.values() if len(socs) > 1)
    return total_groups, contested


def gather_fail_rate(entries: list[dict]) -> float:
    """Same formula as analyze_congestion_fix.py's gather_stats - reused, not reimplemented."""
    success, fail = 0, 0
    for e in entries:
        if e["action"] != "GATHER":
            continue
        if e["success"]:
            success += 1
        else:
            fail += 1
    total = success + fail
    return (fail / total * 100) if total else 0.0


def analyze(path: Path) -> dict:
    entries = load_entries(path)
    cluster = society_clusters(entries)
    n_societies = len(set(cluster.values()))
    tick_span = (entries[-1]["tick"] - entries[0]["tick"]) if entries else 0
    deaths = sum(1 for e in entries if e["action"] == "DEATH")

    total, total_ok, cross, cross_ok = cross_society_trades(entries, cluster)
    groups, contested = cross_society_contention(entries, cluster)

    return {
        "path": path.name,
        "ticks": tick_span,
        "societies": n_societies,
        "deaths": deaths,
        "gather_fail_pct": gather_fail_rate(entries),
        "trades_total": total,
        "trades_cross_pct": (cross / total * 100) if total else 0.0,
        "trades_cross_success_pct": (cross_ok / cross * 100) if cross else 0.0,
        "contention_groups": groups,
        "contention_cross_pct": (contested / groups * 100) if groups else 0.0,
        "contention_per_1k_ticks": (contested / tick_span * 1000) if tick_span else 0.0,
    }


def main(paths: list[str]) -> None:
    rows = [analyze(Path(p)) for p in paths]

    print(f"{'log':<28} {'ticks':>7} {'socs':>5} {'deaths':>7} {'gfail%':>7} "
          f"{'trades':>7} {'x-soc%':>7} {'x-ok%':>6} {'x-cont%':>8} {'x-cont/1k':>10}")
    print("-" * 108)
    for r in rows:
        print(f"{r['path']:<28} {r['ticks']:>7} {r['societies']:>5} {r['deaths']:>7} "
              f"{r['gather_fail_pct']:>6.1f}% {r['trades_total']:>7} "
              f"{r['trades_cross_pct']:>6.1f}% {r['trades_cross_success_pct']:>5.1f}% "
              f"{r['contention_cross_pct']:>7.1f}% {r['contention_per_1k_ticks']:>9.1f}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python3 analyze_cross_society.py run1.jsonl [run2.jsonl ...]")
        sys.exit(1)
    main(sys.argv[1:])
