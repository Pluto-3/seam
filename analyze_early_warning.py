"""Angle 1 of ANALYSIS.md: critical slowing down / early-warning signals.

Every run collapsed in the same narrow window (first 1,000-2,000 ticks).
The periodic stats CSV (one row per 30 real seconds) is too coarse to see
that window in detail - reconstructs a tick-resolution population/hunger
series directly from the raw full_log instead (every alive agent logs
one entry per tick, so this is exact, not sampled), then tests for the
two classic signatures of an approaching critical transition (see
ANALYSIS.md's sources): rising variance and rising lag-1 autocorrelation
in the lead-up to the crash.

Only scans up to a tick ceiling (the crash window), not the whole
multi-GB file - the log is tick-ordered, so this exits early rather than
streaming gigabytes it doesn't need.

Usage: python3 analyze_early_warning.py run.jsonl [run2.jsonl ...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

TICK_CEILING = 5000   # crash happens well inside this in every run so far
ROLL_WINDOW = 100      # ticks, for the rolling variance/autocorrelation


def analyze(path: Path) -> None:
    print(f"\n{'=' * 70}\n{path.name}\n{'=' * 70}")

    hunger_by_tick: dict[int, list[float]] = {}
    alive_ids: set[str] = set()
    pop_by_tick: dict[int, int] = {}

    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e["tick"] > TICK_CEILING:
                break
            aid = e["agent_id"]
            after = e.get("state_after", {})
            if e["action"] == "DEATH" or after.get("alive") is False:
                alive_ids.discard(aid)
            else:
                alive_ids.add(aid)
            h = after.get("hunger")
            if h is not None:
                hunger_by_tick.setdefault(e["tick"], []).append(h)
            pop_by_tick[e["tick"]] = len(alive_ids)

    ticks = sorted(pop_by_tick.keys())
    if len(ticks) < ROLL_WINDOW * 2:
        print("not enough tick-resolution data in the crash window - skipping")
        return

    pop = np.array([pop_by_tick[t] for t in ticks], dtype=float)
    avg_hunger = np.array([np.mean(hunger_by_tick[t]) if hunger_by_tick.get(t) else np.nan for t in ticks])

    # find the crash: steepest population decline
    decline = -np.diff(pop)
    crash_idx = int(np.argmax(np.convolve(decline, np.ones(50), mode="valid")))
    crash_tick = ticks[crash_idx]
    print(f"population trajectory reconstructed for ticks 0-{ticks[-1]} ({len(ticks)} tick-resolution points)")
    print(f"steepest 50-tick decline window centered near tick {crash_tick} (pop {pop[0]:.0f} -> {pop[-1]:.0f} by tick {ticks[-1]})")

    # rolling variance and lag-1 autocorrelation of hunger, in the lead-up to the crash
    lead_up = avg_hunger[:crash_idx] if crash_idx > ROLL_WINDOW * 2 else avg_hunger[:len(avg_hunger) // 2]
    lead_up = lead_up[~np.isnan(lead_up)]
    if len(lead_up) < ROLL_WINDOW * 2:
        print("not enough clean lead-up data to test for early-warning signatures")
        return

    n_windows = len(lead_up) // ROLL_WINDOW
    variances, autocorrs = [], []
    for i in range(n_windows):
        w = lead_up[i * ROLL_WINDOW:(i + 1) * ROLL_WINDOW]
        variances.append(np.var(w))
        if len(w) > 1 and np.std(w) > 0:
            autocorrs.append(np.corrcoef(w[:-1], w[1:])[0, 1])
        else:
            autocorrs.append(np.nan)

    print(f"\nhunger variance across {n_windows} successive {ROLL_WINDOW}-tick windows leading up to the crash:")
    print(" ", [f"{v:.1f}" for v in variances])
    print(f"lag-1 autocorrelation across the same windows:")
    print(" ", [f"{a:.2f}" if not np.isnan(a) else "nan" for a in autocorrs])

    if len(variances) >= 3:
        trend = np.polyfit(range(len(variances)), variances, 1)[0]
        print(f"\nvariance trend (slope, positive = rising toward the crash): {trend:+.2f}")
    valid_ac = [a for a in autocorrs if not np.isnan(a)]
    if len(valid_ac) >= 3:
        ac_trend = np.polyfit(range(len(valid_ac)), valid_ac, 1)[0]
        print(f"autocorrelation trend (slope, positive = classic early-warning signature): {ac_trend:+.4f}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python3 analyze_early_warning.py run1.jsonl [run2.jsonl ...]")
        sys.exit(1)
    for p in sys.argv[1:]:
        analyze(Path(p))
