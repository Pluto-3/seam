"""Analysis of the batch data collected 2026-07-15 in logs/batch, logs/batch_notrade,
logs/longhorizon. Reads only the CSV stat snapshots for the aggregate goals (fast);
streams JSONL only where per-action detail is actually needed (gather contention).

Goals, set before looking at any numbers:
  1. Quantify trade's effect on specialization index and population survival across
     all 20 paired seeds (trade-on vs trade-off), not just the single seed in the
     original Phase 0 finding.
  2. Characterize population survival distribution across the 20 trade-on seeds -
     how common is seed-7-style collapse.
  3. Check the 3 long-horizon seeds (40,000 ticks) for stabilizing/drifting/
     degrading behavior vs. their tick-8000 checkpoint, plus a determinism
     cross-check against the corresponding short run.
  4. Quantify gather attempt/failure rates across all 20 trade-on seeds.
"""

from __future__ import annotations

import csv
import json
import statistics
from pathlib import Path

BATCH_DIR = Path("logs/batch")
NOTRADE_DIR = Path("logs/batch_notrade")
LONGHORIZON_DIR = Path("logs/longhorizon")
SEEDS = list(range(1, 21))


def load_stats(path: Path) -> list[dict]:
    rows = []
    with open(path) as f:
        for row in csv.DictReader(f):
            parsed = {}
            for k, v in row.items():
                if "." in v:
                    parsed[k] = float(v)
                else:
                    parsed[k] = int(v)
            rows.append(parsed)
    return rows


def final_row(path: Path) -> dict:
    return load_stats(path)[-1]


def goal1_trade_effect():
    print("=" * 70)
    print("GOAL 1: trade's effect on specialization index + population (n=20, paired)")
    print("=" * 70)

    on = {s: final_row(BATCH_DIR / f"seed{s}_stats.csv") for s in SEEDS}
    off = {s: final_row(NOTRADE_DIR / f"seed{s}_stats.csv") for s in SEEDS}

    spec_on = [on[s]["specialization_index"] for s in SEEDS]
    spec_off = [off[s]["specialization_index"] for s in SEEDS]
    spec_diff = [a - b for a, b in zip(spec_on, spec_off)]

    pop_on = [on[s]["population"] for s in SEEDS]
    pop_off = [off[s]["population"] for s in SEEDS]

    print(f"\nspecialization index:")
    print(f"  trade-on:  mean={statistics.mean(spec_on):.3f}  stdev={statistics.stdev(spec_on):.3f}  "
          f"min={min(spec_on):.3f}  max={max(spec_on):.3f}")
    print(f"  trade-off: mean={statistics.mean(spec_off):.3f}  stdev={statistics.stdev(spec_off):.3f}  "
          f"min={min(spec_off):.3f}  max={max(spec_off):.3f}")
    print(f"  paired diff (on - off): mean={statistics.mean(spec_diff):.3f}  stdev={statistics.stdev(spec_diff):.3f}")
    beat = sum(1 for d in spec_diff if d > 0)
    print(f"  trade-on > trade-off in {beat}/20 seeds")

    print(f"\npopulation (out of 40):")
    print(f"  trade-on:  mean={statistics.mean(pop_on):.1f}  stdev={statistics.stdev(pop_on):.1f}  "
          f"min={min(pop_on)}  max={max(pop_on)}")
    print(f"  trade-off: mean={statistics.mean(pop_off):.1f}  stdev={statistics.stdev(pop_off):.1f}  "
          f"min={min(pop_off)}  max={max(pop_off)}")

    return {"spec_on": spec_on, "spec_off": spec_off, "spec_diff": spec_diff,
            "pop_on": pop_on, "pop_off": pop_off, "on": on, "off": off}


def goal2_survival_distribution(on: dict):
    print("\n" + "=" * 70)
    print("GOAL 2: population survival distribution across 20 trade-on seeds")
    print("=" * 70)

    pop = {s: on[s]["population"] for s in SEEDS}
    healthy = {s: p for s, p in pop.items() if p >= 35}
    moderate = {s: p for s, p in pop.items() if 20 <= p < 35}
    collapsed = {s: p for s, p in pop.items() if p < 20}

    print(f"\nhealthy (>=35/40 alive):   {len(healthy)}/20 seeds - {sorted(healthy.keys())}")
    print(f"moderate (20-34/40 alive): {len(moderate)}/20 seeds - {sorted(moderate.keys())}")
    print(f"collapsed (<20/40 alive):  {len(collapsed)}/20 seeds - {sorted(collapsed.keys())}")
    print(f"\nfull distribution: {dict(sorted(pop.items()))}")


def goal3_long_horizon():
    print("\n" + "=" * 70)
    print("GOAL 3: long-horizon drift (seeds 1, 7, 42 pushed to 40,000 ticks)")
    print("=" * 70)

    for s in [1, 7, 42]:
        lh_rows = load_stats(LONGHORIZON_DIR / f"seed{s}_stats.csv")
        row_8k = min(lh_rows, key=lambda r: abs(r["tick"] - 8000))
        row_final = lh_rows[-1]

        print(f"\nseed {s}:")

        short_path = BATCH_DIR / f"seed{s}_stats.csv"
        if short_path.exists():
            short_final = final_row(short_path)
            print(f"  determinism check - short run @ tick 8000: pop={short_final['population']} "
                  f"spec={short_final['specialization_index']:.3f} trades_cum={short_final['trades_cum']}")
            print(f"  determinism check - long run  @ tick {row_8k['tick']}: pop={row_8k['population']} "
                  f"spec={row_8k['specialization_index']:.3f} trades_cum={row_8k['trades_cum']}")
            match = (short_final["population"] == row_8k["population"]
                     and abs(short_final["specialization_index"] - row_8k["specialization_index"]) < 1e-9
                     and short_final["trades_cum"] == row_8k["trades_cum"])
            print(f"  EXACT MATCH: {match}")
        else:
            print(f"  determinism check: skipped - seed {s} has no corresponding short run in logs/batch/")

        print(f"  @ tick 8000  -> pop={row_8k['population']} spec={row_8k['specialization_index']:.3f} "
              f"trades_cum={row_8k['trades_cum']} avg_food={row_8k['avg_food']:.1f}")
        print(f"  @ tick 40000 -> pop={row_final['population']} spec={row_final['specialization_index']:.3f} "
              f"trades_cum={row_final['trades_cum']} avg_food={row_final['avg_food']:.1f}")


def goal4_gather_contention():
    print("\n" + "=" * 70)
    print("GOAL 4: gather attempt/failure rates across all 20 trade-on seeds")
    print("=" * 70)

    results = {}
    for s in SEEDS:
        path = BATCH_DIR / f"seed{s}.jsonl"
        success, fail = 0, 0
        with open(path) as f:
            for line in f:
                if '"action": "GATHER"' not in line:
                    continue
                e = json.loads(line)
                if e["action"] != "GATHER":
                    continue
                if e["success"]:
                    success += 1
                else:
                    fail += 1
        total = success + fail
        fail_rate = fail / total if total else 0.0
        results[s] = (success, fail, fail_rate)
        print(f"  seed {s:2d}: {total:6d} attempts, {success:6d} succeeded, {fail:5d} failed "
              f"({fail_rate*100:5.1f}% fail rate)")

    fail_rates = [r[2] for r in results.values()]
    print(f"\nfail rate across seeds: mean={statistics.mean(fail_rates)*100:.1f}%  "
          f"stdev={statistics.stdev(fail_rates)*100:.1f}%  "
          f"min={min(fail_rates)*100:.1f}%  max={max(fail_rates)*100:.1f}%")
    high_contention = {s: r[2] for s, r in results.items() if r[2] > 0.15}
    print(f"seeds with >15% gather fail rate: {sorted(high_contention.keys())} -> "
          f"{[f'{v*100:.1f}%' for v in high_contention.values()]}")

    return results


if __name__ == "__main__":
    g1 = goal1_trade_effect()
    goal2_survival_distribution(g1["on"])
    goal3_long_horizon()
    goal4_gather_contention()
