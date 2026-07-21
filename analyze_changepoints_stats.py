"""Changepoint detection adapted from analyze_changepoints.py's technique
(ruptures' PELT, L2 cost, penalized so it doesn't overfit noise) for a run
that has no raw tick-level JSONL log - only the periodic stats.csv this
project's serve --stats-csv flag already produces. Coarser resolution
(~149-tick rows here, vs. the original script's 250-tick bins built from a
full log) but real data, not synthetic.

Usage: python3 analyze_changepoints_stats.py stats.csv [column]
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import ruptures as rpt


def load_column(path: Path, column: str) -> tuple[np.ndarray, np.ndarray]:
    import csv

    ticks, values = [], []
    with open(path) as f:
        for row in csv.DictReader(f):
            ticks.append(int(row["tick"]))
            values.append(float(row[column]))
    return np.array(ticks), np.array(values)


def analyze(path: Path, column: str) -> None:
    ticks, series = load_column(path, column)
    print(f"\n{'=' * 70}\n{path.name} - column: {column}\n{'=' * 70}")
    print(f"{len(series)} real rows, tick range {ticks[0]}-{ticks[-1]}")

    algo = rpt.Pelt(model="l2", min_size=4).fit(series.reshape(-1, 1))
    penalty = 3 * np.log(len(series)) * np.var(series)
    breakpoints = algo.predict(pen=penalty)

    print(f"\ndetected changepoints (real tick range, before/after mean {column}):")
    prev = 0
    for bp in breakpoints:
        segment = series[prev:bp]
        tick_start = ticks[prev]
        tick_end = ticks[bp - 1] if bp < len(ticks) else ticks[-1]
        print(f"  ticks {tick_start:>7} - {tick_end:>7} ({len(segment):>4} rows): mean {column}={segment.mean():.4f} (std={segment.std():.4f})")
        prev = bp

    if len(breakpoints) <= 1:
        print(f"  (no real changepoint found - {column} stayed statistically flat the whole run)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python3 analyze_changepoints_stats.py stats.csv [column]")
        sys.exit(1)
    col = sys.argv[2] if len(sys.argv) > 2 else "specialization_index"
    analyze(Path(sys.argv[1]), col)
