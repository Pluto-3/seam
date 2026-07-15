"""Full 20-seed before/after comparison for the congestion fix (commit b09cf53).
logs/batch = before (original baseline). logs/batch_post_fix = after.
"""

from __future__ import annotations

import csv
import json
import statistics
from pathlib import Path

BEFORE_DIR = Path("logs/batch")
AFTER_DIR = Path("logs/batch_post_fix")
SEEDS = list(range(1, 21))


def final_row(path: Path) -> dict:
    with open(path) as f:
        rows = list(csv.DictReader(f))
    parsed = {}
    for k, v in rows[-1].items():
        parsed[k] = float(v) if "." in v else int(v)
    return parsed


def gather_stats(path: Path) -> tuple[int, int, float]:
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
    return success, fail, (fail / total * 100 if total else 0.0)


before_pop, after_pop = [], []
before_spec, after_spec = [], []
before_trades, after_trades = [], []
before_fail, after_fail = [], []

print(f"{'seed':>4} | {'pop before->after':^20} | {'spec before->after':^22} | "
      f"{'trades before->after':^24} | {'fail% before->after':^22}")
print("-" * 100)

for s in SEEDS:
    b = final_row(BEFORE_DIR / f"seed{s}_stats.csv")
    a = final_row(AFTER_DIR / f"seed{s}_stats.csv")
    _, _, bf = gather_stats(BEFORE_DIR / f"seed{s}.jsonl")
    _, _, af = gather_stats(AFTER_DIR / f"seed{s}.jsonl")

    before_pop.append(b["population"]); after_pop.append(a["population"])
    before_spec.append(b["specialization_index"]); after_spec.append(a["specialization_index"])
    before_trades.append(b["trades_cum"]); after_trades.append(a["trades_cum"])
    before_fail.append(bf); after_fail.append(af)

    print(f"{s:>4} | {b['population']:>3} -> {a['population']:<3}          | "
          f"{b['specialization_index']:.3f} -> {a['specialization_index']:.3f}        | "
          f"{b['trades_cum']:>7} -> {a['trades_cum']:<7}       | "
          f"{bf:>5.1f} -> {af:<5.1f}")

print()
print("=" * 60)
print("SUMMARY (n=20)")
print("=" * 60)
print(f"population:  before mean={statistics.mean(before_pop):.1f} stdev={statistics.stdev(before_pop):.1f}  "
      f"|  after mean={statistics.mean(after_pop):.1f} stdev={statistics.stdev(after_pop):.1f}")
print(f"  seeds at 40/40: before={sum(1 for p in before_pop if p==40)}/20  after={sum(1 for p in after_pop if p==40)}/20")
print(f"  worse after fix: {sum(1 for b,a in zip(before_pop,after_pop) if a<b)}/20")
print(f"  better after fix: {sum(1 for b,a in zip(before_pop,after_pop) if a>b)}/20")
print(f"  unchanged: {sum(1 for b,a in zip(before_pop,after_pop) if a==b)}/20")

print()
print(f"specialization index: before mean={statistics.mean(before_spec):.3f}  after mean={statistics.mean(after_spec):.3f}")
print(f"  higher after fix: {sum(1 for b,a in zip(before_spec,after_spec) if a>b)}/20")

print()
print(f"cumulative trades: before mean={statistics.mean(before_trades):.0f}  after mean={statistics.mean(after_trades):.0f}")
print(f"  higher after fix: {sum(1 for b,a in zip(before_trades,after_trades) if a>b)}/20")

print()
print(f"gather fail rate: before mean={statistics.mean(before_fail):.1f}%  after mean={statistics.mean(after_fail):.1f}%")
print(f"  lower after fix: {sum(1 for b,a in zip(before_fail,after_fail) if a<b)}/20")
print(f"  min/max after: {min(after_fail):.1f}% / {max(after_fail):.1f}%")
