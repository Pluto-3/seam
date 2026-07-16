"""Strategy exporter (Phase 3, specialty gap closed Phase 5): mines a run's
log for what actually correlates with doing well, and can compare two runs
the same way the congestion-fix analysis did by hand. Read-only, same as
every exporter.

Reinterpreted from the original design doc on purpose (see DESIGN.md / plan
for the full reasoning): crowd agents don't carry varying weight-sets to
compare, so "strategy" here means mining which *agents* did well and what
distinguished them, not comparing hypothetical policy variants.

A real limitation from v1, closed for v2 runs rather than worked around:
agent `specialty` was never part of the logged schema (agents.py's
snapshot() doesn't include it), so specialization index couldn't be
recomputed from the JSONL alone - compare mode had to fall back to a
paired `_stats.csv` file for that one metric. Postgres's `events` table now
logs specialty directly (see core-rs/schema.sql), so v2 runs compute it
straight from the event stream, same formula as `stats.rs`'s
specialization_index. v1 JSONL mode keeps the old paired-CSV fallback
unchanged - nothing about that limitation was fabricated away, it just
doesn't apply to the new data.

    python export_strategy.py single --log-path logs/batch_post_fix/seed7.jsonl
    python export_strategy.py single --postgres-url "dbname=seam" --run-id run-123
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


def read_events_from_jsonl(log_path: str):
    with open(log_path) as f:
        for line in f:
            yield json.loads(line)


def read_events_from_postgres(postgres_url: str, run_id: str):
    import psycopg2
    import psycopg2.extras

    conn = psycopg2.connect(postgres_url)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT tick, agent_id, tier, specialty, action, target, success, state_after, delta "
                "FROM events WHERE run_id = %s ORDER BY tick",
                (run_id,),
            )
            for row in cur:
                yield dict(row)
    finally:
        conn.close()


def _specialization_index(agent_last: dict, agent_specialty: dict) -> float | None:
    """Same formula as core-rs/src/stats.rs's specialization_index: for each
    alive agent with real holdings, what fraction of their inventory is
    outside their own specialty - averaged across agents. None if specialty
    isn't known for anyone (v1 JSONL mode)."""
    fractions = []
    for aid, state in agent_last.items():
        specialty = agent_specialty.get(aid)
        if not specialty or not state.get("alive"):
            continue
        inv = state.get("inventory", {})
        total = sum(inv.get(r, 0.0) for r in RAW_RESOURCES)
        if total <= 0:
            continue
        non_specialty = total - inv.get(specialty, 0.0)
        fractions.append(non_specialty / total)
    return sum(fractions) / len(fractions) if fractions else None


def _scan_events(entries):
    """One pass over the event stream: per-agent final state + action
    counts, plus run-wide gather/trade/craft/death tallies."""
    agent_last: dict[str, dict] = {}
    agent_specialty: dict[str, str] = {}
    agent_actions: dict[str, Counter] = {}
    gather_success, gather_fail = 0, 0
    trade_count = 0
    craft_count = 0
    death_count = 0
    max_tick = 0

    for e in entries:
        aid = e["agent_id"]
        max_tick = max(max_tick, e["tick"])
        agent_last[aid] = e["state_after"]
        if e.get("specialty"):
            agent_specialty[aid] = e["specialty"]
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
        "agent_last": agent_last, "agent_specialty": agent_specialty, "agent_actions": agent_actions,
        "gather_success": gather_success, "gather_fail": gather_fail,
        "trade_count": trade_count, "craft_count": craft_count,
        "death_count": death_count, "max_tick": max_tick,
        "specialization_index": _specialization_index(agent_last, agent_specialty),
    }


def _wealth(state: dict) -> float:
    inv = state.get("inventory", {})
    return sum(inv.get(r, 0.0) for r in RAW_RESOURCES)


def single_run(entries, source_label: str) -> None:
    scan = _scan_events(entries)
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

    print(f"=== single-run strategy report: {source_label} ===")
    print(f"agents: {n}  alive at end: {alive_count}  ticks: {scan['max_tick']}")
    print(f"run totals: {int(scan['trade_count'])} trades, {scan['craft_count']} crafts, "
          f"{scan['death_count']} deaths, gather fail rate "
          f"{scan['gather_fail'] / max(1, scan['gather_success'] + scan['gather_fail']) * 100:.1f}%")
    if scan["specialization_index"] is not None:
        print(f"specialization index: {scan['specialization_index']:.3f} (computed directly - specialty was logged)")
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
    before = _scan_events(read_events_from_jsonl(before_path))
    after = _scan_events(read_events_from_jsonl(after_path))

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

    if before["specialization_index"] is not None and after["specialization_index"] is not None:
        print(f"specialization index:      {before['specialization_index']:.3f} -> {after['specialization_index']:.3f}  "
              f"(computed directly - specialty was logged)")
        return

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
    single_p.add_argument("--log-path", default=None, help="v1-style JSONL log")
    single_p.add_argument("--postgres-url", default=None, help="v2 alternative to --log-path, e.g. 'dbname=seam'")
    single_p.add_argument("--run-id", default=None, help="required with --postgres-url")

    compare_p = sub.add_parser("compare")
    compare_p.add_argument("--before", required=True)
    compare_p.add_argument("--after", required=True)

    args = p.parse_args()
    if args.mode == "single":
        if bool(args.log_path) == bool(args.postgres_url):
            single_p.error("pass exactly one of --log-path or --postgres-url")
        if args.postgres_url and not args.run_id:
            single_p.error("--postgres-url requires --run-id")
        if args.log_path:
            single_run(read_events_from_jsonl(args.log_path), args.log_path)
        else:
            single_run(read_events_from_postgres(args.postgres_url, args.run_id), f"postgres:{args.run_id}")
    else:
        compare(args.before, args.after)


if __name__ == "__main__":
    main()
