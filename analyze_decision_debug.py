"""Angle 6 follow-up: does decision_debug show the hotspot node's dominance
is really the food-routing problem the two original hypotheses were staged
to test, or something those hypotheses can't see at all?

Real blind spot found by rereading decide.rs before writing this: every
tick's candidate set includes GATHER, MOVE, CRAFT, REST, CONSUME, SIGNAL,
*and* TRADE, but decision_debug only ever captured gather/move/food-move
scores - never trade_score. TRADE candidates are generated pairwise for
every co-located agent, so a crowded node mechanically produces far more
trade opportunities than a quiet one, regardless of food quality. That's a
structurally different mechanism (trade-attraction trap) than "food
alternatives are invisible to a 1-hop lookahead" (food-visibility trap).
No new instrumentation needed to check this - every entry already carries
`action`, so [2] below cross-tabulates action-type by node directly.

Also, since this project's own "critical re-pass" (see project memory)
already caught one aggregate-number-hides-the-real-story mistake this same
investigation, this script deliberately doesn't stop at one number:

  [1] reconfirms the headline hotspot/death-concentration finding on
      *this* run's data rather than assuming it carries over
  [2] action-type breakdown at the hotspot vs rest-of-graph, plus what
      share of ALL trades in the run happened there (trade-attraction
      angle)
  [3] time-windowed hotspot share (population plateaued instead of
      collapsing this run, unlike the long runs behind the original
      finding - worth checking if the grip loosens as the crowd thins)
  [4] the two original hypotheses, stratified by specialty and by
      congestion level instead of one aggregate win-rate/null-rate

Usage: python3 analyze_decision_debug.py run1.jsonl [run2.jsonl ...]
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

TICK_BUCKET = 10_000  # fixed bucket size so bucket count scales with run length, not a fixed count
CONGESTION_BUCKETS = [(0, 5, "low occ <5"), (5, 15, "med occ 5-14"), (15, 10**9, "high occ 15+")]


def congestion_bucket(occ: int) -> str:
    for lo, hi, label in CONGESTION_BUCKETS:
        if lo <= occ < hi:
            return label
    return "?"


def pct(n: int, d: int) -> float:
    return (n / d * 100) if d else 0.0


def analyze(path: Path) -> dict:
    print(f"\n{'=' * 78}\n{path.name}\n{'=' * 78}")

    presence: dict[str, int] = defaultdict(int)
    deaths: dict[str, int] = defaultdict(int)
    trades_by_node: dict[str, int] = defaultdict(int)
    action_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    time_bucket_node: dict[tuple, int] = defaultdict(int)
    time_bucket_total: dict[int, int] = defaultdict(int)
    death_time_bucket: dict[tuple, int] = defaultdict(int)

    # node -> [dd_total, gather_present, food_move_present, gather_beats_food]
    dd_node: dict[str, list] = defaultdict(lambda: [0, 0, 0, 0])
    dd_specialty: dict[tuple, list] = defaultdict(lambda: [0, 0, 0, 0])
    dd_congestion: dict[tuple, list] = defaultdict(lambda: [0, 0, 0, 0])

    total_actions = 0
    total_trades = 0
    bad_lines = 0

    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                bad_lines += 1
                continue
            total_actions += 1
            action = e.get("action", "?")
            tick = e.get("tick", 0)
            bucket = tick // TICK_BUCKET
            loc_after = e.get("state_after", {}).get("location")
            loc_before = e.get("state_before", {}).get("location")
            loc = loc_after or loc_before

            if loc:
                presence[loc] += 1
                action_counts[loc][action] += 1
                time_bucket_node[(loc, bucket)] += 1
            time_bucket_total[bucket] += 1

            if action == "DEATH" and loc:
                deaths[loc] += 1
                death_time_bucket[(loc, bucket)] += 1
            if action == "TRADE":
                total_trades += 1
                if loc:
                    trades_by_node[loc] += 1

            dd = e.get("decision_debug")
            if dd and loc_before:
                gather = dd.get("gather_score")
                food_move = dd.get("best_food_move_score")
                specialty = dd.get("specialty", "?")
                occ = dd.get("location_occupancy", 0)
                cong_label = congestion_bucket(occ)
                gp = gather is not None
                fp = food_move is not None
                beats = 1 if (gp and fp and gather > food_move) else 0

                row = dd_node[loc_before]
                row[0] += 1
                row[1] += int(gp)
                row[2] += int(fp)
                row[3] += beats

                srow = dd_specialty[(loc_before, specialty)]
                srow[0] += 1
                srow[1] += int(gp)
                srow[2] += int(fp)
                srow[3] += beats

                crow = dd_congestion[(loc_before, cong_label)]
                crow[0] += 1
                crow[1] += int(gp)
                crow[2] += int(fp)
                crow[3] += beats

    if not presence:
        print("no data")
        return {}

    ranked = sorted(presence.keys(), key=lambda n: -presence[n])
    top_node = ranked[0]
    top_share = pct(presence[top_node], total_actions)
    total_deaths = sum(deaths.values())
    top_deaths = deaths.get(top_node, 0)
    death_share = pct(top_deaths, total_deaths)

    print(f"\n[1] HEADLINE RECONFIRMATION  ({total_actions} actions, {bad_lines} unparsable lines skipped)")
    print(f"  top node: {top_node} - {presence[top_node]} actions, {top_share:.1f}% of all logged activity")
    print(f"  top 5 nodes: {[(n, f'{pct(presence[n], total_actions):.1f}%') for n in ranked[:5]]}")
    print(f"  deaths at {top_node}: {top_deaths}/{total_deaths} ({death_share:.1f}% of all deaths)")

    print(f"\n[2] ACTION-TYPE BREAKDOWN: {top_node} vs rest-of-graph")
    top_actions = action_counts[top_node]
    top_total = sum(top_actions.values())
    rest_actions: dict[str, int] = defaultdict(int)
    for n, counts in action_counts.items():
        if n == top_node:
            continue
        for a, c in counts.items():
            rest_actions[a] += c
    rest_total = sum(rest_actions.values())
    all_kinds = sorted(set(top_actions) | set(rest_actions))
    print(f"  {'action':<10} {'@' + top_node:>14} {'rest-of-graph':>16}")
    for a in all_kinds:
        tp = pct(top_actions.get(a, 0), top_total)
        rp = pct(rest_actions.get(a, 0), rest_total)
        print(f"  {a:<10} {tp:>13.1f}% {rp:>15.1f}%")
    trade_share_top = pct(trades_by_node.get(top_node, 0), total_trades)
    print(f"  -> {trades_by_node.get(top_node, 0)}/{total_trades} ({trade_share_top:.1f}%) of ALL trades this run happened at {top_node}")
    top_gather_pct = pct(top_actions.get("GATHER", 0), top_total)
    top_trade_pct = pct(top_actions.get("TRADE", 0), top_total)
    if top_trade_pct > top_gather_pct:
        print(f"  -> at {top_node} itself, TRADE ({top_trade_pct:.1f}%) outweighs GATHER ({top_gather_pct:.1f}%) - trade-attraction, not just food-routing")
    else:
        print(f"  -> at {top_node} itself, GATHER ({top_gather_pct:.1f}%) still outweighs TRADE ({top_trade_pct:.1f}%)")

    print(f"\n[3] TIME-WINDOWED {top_node} SHARE (bucket = {TICK_BUCKET} ticks)")
    buckets = sorted(b for (n, b) in time_bucket_node if n == top_node)
    print(f"  {'tick range':<18} {top_node + ' share':>12} {'deaths here':>12}")
    for b in buckets:
        lo, hi = b * TICK_BUCKET, (b + 1) * TICK_BUCKET
        share = pct(time_bucket_node.get((top_node, b), 0), time_bucket_total.get(b, 0))
        d = death_time_bucket.get((top_node, b), 0)
        print(f"  {lo:>8}-{hi:<8} {share:>11.1f}% {d:>12}")

    print(f"\n[4] DECISION_DEBUG HYPOTHESES AT {top_node} (stratified, not aggregate)")
    total_dd, gp_dd, fp_dd, beats_dd = dd_node.get(top_node, [0, 0, 0, 0])
    print(f"  overall: {total_dd} decisions logged here")
    print(f"    best_food_move_score present (non-null): {pct(fp_dd, total_dd):.1f}%  ->  null rate: {pct(total_dd - fp_dd, total_dd):.1f}%")
    print(f"    gather_score present: {pct(gp_dd, total_dd):.1f}%")
    print(f"    gather_score > best_food_move_score (of all decisions here, incl. cases where food_move was null i.e. trivially 'beats'): {pct(beats_dd, total_dd):.1f}%")

    print(f"\n  by specialty:")
    print(f"  {'specialty':<12} {'n':>7} {'food_move null%':>17} {'gather beats%':>15}")
    for (n, specialty), (t, gp, fp, beats) in sorted(dd_specialty.items()):
        if n != top_node:
            continue
        print(f"  {specialty:<12} {t:>7} {pct(t - fp, t):>16.1f}% {pct(beats, t):>14.1f}%")

    print(f"\n  by congestion level (occupancy at decision time):")
    print(f"  {'level':<14} {'n':>7} {'food_move null%':>17} {'gather beats%':>15}")
    for (n, label), (t, gp, fp, beats) in sorted(dd_congestion.items()):
        if n != top_node:
            continue
        print(f"  {label:<14} {t:>7} {pct(t - fp, t):>16.1f}% {pct(beats, t):>14.1f}%")

    return {
        "run": path.name,
        "top_node": top_node,
        "top_share_pct": round(top_share, 1),
        "death_share_pct": round(death_share, 1),
        "trade_share_top_pct": round(trade_share_top, 1),
        "top_gather_pct": round(top_gather_pct, 1),
        "top_trade_pct": round(top_trade_pct, 1),
        "dd_total": total_dd,
        "food_move_null_pct": round(pct(total_dd - fp_dd, total_dd), 1),
        "gather_beats_food_pct": round(pct(beats_dd, total_dd), 1),
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python3 analyze_decision_debug.py run1.jsonl [run2.jsonl ...]")
        sys.exit(1)

    summaries = []
    for p in sys.argv[1:]:
        summaries.append(analyze(Path(p)))

    if len(summaries) > 1:
        print(f"\n{'=' * 78}\nCROSS-RUN COMPARISON\n{'=' * 78}")
        cols = ["run", "top_node", "top_share_pct", "death_share_pct", "trade_share_top_pct", "top_gather_pct", "top_trade_pct", "food_move_null_pct", "gather_beats_food_pct"]
        print("  " + " | ".join(f"{c:>20}" for c in cols))
        for s in summaries:
            if not s:
                continue
            print("  " + " | ".join(f"{str(s.get(c, '')):>20}" for c in cols))
