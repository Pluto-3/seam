"""Angle 7 of ANALYSIS.md: precise changepoint detection.

The tick ~37,000-41,000 "trading resurgence" (main/societies4 vs the
flat no-sidecar run) was originally found by eyeballing 25-row samples of
the stats CSV. This replaces that with real changepoint detection
(ruptures' PELT algorithm, penalized for the number of breakpoints so it
doesn't overfit noise) on a tick-binned trade-count series built directly
from the raw log - finer resolution than the 30-second stats CSV snapshots
allow.

Usage: python3 analyze_changepoints.py run.jsonl [run2.jsonl ...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import ruptures as rpt

BIN_SIZE = 250  # ticks per bin - fine enough to localize a transition precisely


def trade_series(path: Path) -> tuple[np.ndarray, int]:
    counts: dict[int, int] = {}
    max_tick = 0
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            e = json.loads(line)
            # Track the real end of the run from every entry, not just trades -
            # a run where trading stops early but ticks keep advancing would
            # otherwise silently report the wrong (truncated) run length.
            max_tick = max(max_tick, e["tick"])
            if e["action"] != "TRADE" or not e["success"]:
                continue
            b = e["tick"] // BIN_SIZE
            counts[b] = counts.get(b, 0) + 1
    n_bins = max_tick // BIN_SIZE + 1
    series = np.zeros(n_bins)
    for b, c in counts.items():
        series[b] = c
    return series, max_tick


def analyze(path: Path) -> None:
    print(f"\n{'=' * 70}\n{path.name}\n{'=' * 70}")
    series, max_tick = trade_series(path)
    print(f"{len(series)} bins of {BIN_SIZE} ticks each (run length: {max_tick} ticks)")

    # PELT with an L2 cost model - detects shifts in mean trade rate.
    # pen chosen relative to series scale so it doesn't flag every noisy tick.
    algo = rpt.Pelt(model="l2", min_size=4).fit(series.reshape(-1, 1))
    penalty = 3 * np.log(len(series)) * np.var(series)
    breakpoints = algo.predict(pen=penalty)

    print(f"\ndetected changepoints (bin index -> tick, with before/after mean trade rate per {BIN_SIZE} ticks):")
    prev = 0
    for bp in breakpoints:
        segment = series[prev:bp]
        tick_start = prev * BIN_SIZE
        tick_end = bp * BIN_SIZE
        print(f"  ticks {tick_start:>7} - {tick_end:>7}: mean {segment.mean():.1f} trades/{BIN_SIZE}-tick bin")
        prev = bp

    if len(breakpoints) <= 1:
        print("  (no real changepoint found - trade rate stayed statistically flat the whole run)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python3 analyze_changepoints.py run1.jsonl [run2.jsonl ...]")
        sys.exit(1)
    for p in sys.argv[1:]:
        analyze(Path(p))
