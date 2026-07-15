"""Strategy exporter (Phase 3): mines a run's log for what actually correlates
with doing well, and can compare two runs the same way the congestion-fix
analysis did by hand. Read-only, same as every exporter.

Reinterpreted from the original design doc on purpose (see DESIGN.md / plan
for the full reasoning): crowd agents don't carry varying weight-sets to
compare, so "strategy" here means mining which *agents* did well and what
distinguished them, not comparing hypothetical policy variants.

Real limitation, not worked around with a guess: agent `specialty` isn't part
of the logged schema (agents.AgentState.snapshot() doesn't include it), so
specialization index can't be recomputed from the JSONL alone. Compare mode
uses the paired `_stats.csv` file for that one metric when present (the same
file run.py always writes alongside a log, computed live from real agent
objects) and says so plainly when it isn't available, rather than
approximating specialty from gather frequency.

    python export_strategy.py single --log-path logs/batch_post_fix/seed7.jsonl
    python export_strategy.py compare --before logs/batch/seed7.jsonl --after logs/batch_post_fix/seed7.jsonl
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from collections import Counter

RAW_RESOURCES = ("ore", "food", "wood")


def _paired_stats_csv(jsonl_path: str) -> str | None:
    base = jsonl_path[:-len(".jsonl")] if jsonl_path.endswith(".jsonl") else jsonl_path
    candidate = base + "_stats.csv"
    return candidate if os.path.exists(candidate) else None


def _final_stats_row(csv_path: str) -> dict:
    with open(csv_path) as f:
        rows = list(csv.DictReader(f))
    row = rows[-1]
    return {k: (float(v) if "." in v else int(v)) for k, v in row.items()}


def _scan_log(jsonl_path: str):
    """One pass over the log: per-agent final state + action counts, plus
    run-wide gather/trade/craft/death tallies."""
    agent_last: dict[str, dict] = {}
    agent_actions: dict[str, Counter] = {}
    gather_success, gather_fail = 0, 0
    trade_count = 0
    craft_count = 0
    death_count = 0
    max_tick = 0

    with open(jsonl_path) as f:
        for line in f:
            e = json.loads(line)
            aid = e["agent_id"]
            max_tick = max(max_tick, e["tick"])
            agent_last[aid] = e["state_after"]
            agent_actions.setdefault(aid, Counter())[e["action"]] += 1

            if e["action"] == "GATHER":
                if e["success"]:
                    gather_success += 1
                else:
                    gather_fail += 1
            elif e["action"] == "TRADE" and e["success"]:
                # each successful swap produces two log entries (initiator + responder,
                # see actions.py's resolve_trade_phase) - count swaps, not entries, to
                # match the "trades" convention used everywhere else in this project
                trade_count += 0.5
            elif e["action"] == "CRAFT" and e["success"]:
                craft_count += 1
            elif e["action"] == "DEATH":
                death_count += 1

    return {
        "agent_last": agent_last, "agent_actions": agent_actions,
        "gather_success": gather_success, "gather_fail": gather_fail,
        "trade_count": trade_count, "craft_count": craft_count,
        "death_count": death_count, "max_tick": max_tick,
    }


def _wealth(state: dict) -> float:
    inv = state.get("inventory", {})
    return sum(inv.get(r, 0.0) for r in RAW_RESOURCES)


def single_run(log_path: str) -> None:
    scan = _scan_log(log_path)
    agent_last = scan["agent_last"]

    ranked = sorted(
        agent_last.items(),
        key=lambda item: (item[1].get("alive", False), _wealth(item[1])),
        reverse=True,
    )
    n = len(ranked)
    quartile = max(1, n // 4)
    top = ranked[:quartile]
    bottom = ranked[-quartile:]

    def action_profile(group):
        totals = Counter()
        for aid, _ in group:
            totals.update(scan["agent_actions"][aid])
        total_actions = sum(totals.values()) or 1
        return {action: count / total_actions for action, count in totals.items()}

    alive_count = sum(1 for s in agent_last.values() if s.get("alive"))

    print(f"=== single-run strategy report: {log_path} ===")
    print(f"agents: {n}  alive at end: {alive_count}  ticks: {scan['max_tick']}")
    print(f"run totals: {int(scan['trade_count'])} trades, {scan['craft_count']} crafts, "
          f"{scan['death_count']} deaths, gather fail rate "
          f"{scan['gather_fail'] / max(1, scan['gather_success'] + scan['gather_fail']) * 100:.1f}%")
    print()
    print(f"top quartile ({quartile} agents) — mean wealth {sum(_wealth(s) for _, s in top) / quartile:.1f}:")
    print(f"  action mix: { {k: round(v, 3) for k, v in action_profile(top).items()} }")
    print(f"bottom quartile ({quartile} agents) — mean wealth {sum(_wealth(s) for _, s in bottom) / quartile:.1f}:")
    print(f"  action mix: { {k: round(v, 3) for k, v in action_profile(bottom).items()} }")

    top_trade_share = action_profile(top).get("TRADE", 0.0)
    bottom_trade_share = action_profile(bottom).get("TRADE", 0.0)
    print()
    print(f"trade share: top quartile {top_trade_share:.1%} of actions vs bottom quartile "
          f"{bottom_trade_share:.1%} — {'top-performers trade more' if top_trade_share > bottom_trade_share else 'no clear trade-share edge for top performers'}")


def compare(before_path: str, after_path: str) -> None:
    before = _scan_log(before_path)
    after = _scan_log(after_path)

    before_alive = sum(1 for s in before["agent_last"].values() if s.get("alive"))
    after_alive = sum(1 for s in after["agent_last"].values() if s.get("alive"))
    before_fail_rate = before["gather_fail"] / max(1, before["gather_success"] + before["gather_fail"]) * 100
    after_fail_rate = after["gather_fail"] / max(1, after["gather_success"] + after["gather_fail"]) * 100

    print(f"=== compare: {before_path}  vs  {after_path} ===")
    print(f"population (alive at end): {before_alive} -> {after_alive}")
    print(f"cumulative trades:         {int(before['trade_count'])} -> {int(after['trade_count'])}")
    print(f"cumulative crafts:         {before['craft_count']} -> {after['craft_count']}")
    print(f"deaths:                    {before['death_count']} -> {after['death_count']}")
    print(f"gather fail rate:          {before_fail_rate:.1f}% -> {after_fail_rate:.1f}%")

    before_csv = _paired_stats_csv(before_path)
    after_csv = _paired_stats_csv(after_path)
    if before_csv and after_csv:
        b_spec = _final_stats_row(before_csv)["specialization_index"]
        a_spec = _final_stats_row(after_csv)["specialization_index"]
        print(f"specialization index:      {b_spec:.3f} -> {a_spec:.3f}  "
              f"(from paired _stats.csv files)")
    else:
        missing = before_path if not before_csv else after_path
        print(f"specialization index:      not available - no paired _stats.csv found for {missing} "
              f"(specialty isn't part of the logged schema, can't be recomputed from JSONL alone)")


def main() -> None:
    p = argparse.ArgumentParser(description="seam - strategy exporter")
    sub = p.add_subparsers(dest="mode", required=True)

    single_p = sub.add_parser("single")
    single_p.add_argument("--log-path", required=True)

    compare_p = sub.add_parser("compare")
    compare_p.add_argument("--before", required=True)
    compare_p.add_argument("--after", required=True)

    args = p.parse_args()
    if args.mode == "single":
        single_run(args.log_path)
    else:
        compare(args.before, args.after)


if __name__ == "__main__":
    main()
