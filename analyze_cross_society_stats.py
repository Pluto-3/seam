"""Cross-society comparison from --society-stats-csv, for a run with no raw
JSONL log (analyze_cross_society.py needs that). Three societies ran side
by side in one shared world under near-identical conditions - not a
controlled experiment, but a real check on whether they behaved
independently or one society's story dominated, per this project's own
standing lesson that re-running the same seed isn't real replication (this
*is* three genuinely different trajectories, sharing a world, not the same
seed rerun).

Usage: python3 analyze_cross_society_stats.py societies.csv
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy import stats


def load(path: Path) -> dict[str, dict[str, list]]:
    by_society: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    with open(path) as f:
        for row in csv.DictReader(f):
            s = row["society_id"]
            by_society[s]["tick"].append(int(row["tick"]))
            by_society[s]["population_alive"].append(int(row["population_alive"]))
            by_society[s]["avg_energy"].append(float(row["avg_energy"]))
            by_society[s]["avg_hunger"].append(float(row["avg_hunger"]))
            by_society[s]["total_food_held"].append(float(row["total_food_held"]))
    return by_society


def analyze(path: Path) -> None:
    data = load(path)
    societies = sorted(data)
    print(f"{len(societies)} real societies: {societies}")

    for metric in ["population_alive", "avg_energy", "avg_hunger", "total_food_held"]:
        print(f"\n{'=' * 70}\n{metric}\n{'=' * 70}")
        series = {s: np.array(data[s][metric]) for s in societies}
        for s in societies:
            v = series[s]
            print(f"  {s}: start={v[0]:.2f} end={v[-1]:.2f} mean={v.mean():.2f} std={v.std():.2f} min={v.min():.2f} max={v.max():.2f}")

        # Pairwise correlation - real shared dynamics (e.g. everyone's
        # hunger rising/falling together, a genuinely shared-world effect)
        # vs. independent trajectories.
        n = min(len(series[s]) for s in societies)
        for i, a in enumerate(societies):
            for b in societies[i + 1 :]:
                r, p = stats.pearsonr(series[a][:n], series[b][:n])
                print(f"  corr({a}, {b}) = {r:+.3f} (p={p:.3g})")

    # Population: did any society ever lose an agent? Zero deaths anywhere
    # would be a real, notable finding for the whole run, not just the
    # already-known global 46/46.
    print(f"\n{'=' * 70}\ndeaths check per society\n{'=' * 70}")
    for s in societies:
        v = np.array(data[s]["population_alive"])
        roster = None
        print(f"  {s}: population ranged {v.min():.0f}-{v.max():.0f} across the whole run (never dropped below max = zero deaths)" if v.min() == v.max() else f"  {s}: population dropped from {v.max():.0f} to {v.min():.0f} at some point - real deaths occurred")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python3 analyze_cross_society_stats.py societies.csv")
        sys.exit(1)
    analyze(Path(sys.argv[1]))
