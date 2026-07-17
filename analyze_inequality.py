"""Angle 3 of ANALYSIS.md: wealth/resource inequality (econophysics).

Never measured before this pass. Computes the Gini coefficient of final
resource holdings (a standard inequality measure, 0=perfectly equal,
1=one agent holds everything), per society and over time, and checks
whether inequality predicts survival - does concentration of resources
in a few agents correlate with who dies?

Usage: python3 analyze_inequality.py run.jsonl [run2.jsonl ...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from scipy import stats

CHECKPOINT_SIZE = 10000  # ticks - wealth distribution snapshot cadence


def gini(values: np.ndarray) -> float:
    if len(values) == 0 or values.sum() == 0:
        return 0.0
    v = np.sort(values)
    n = len(v)
    index = np.arange(1, n + 1)
    return float((2 * np.sum(index * v) - (n + 1) * np.sum(v)) / (n * np.sum(v)))


def analyze(path: Path) -> None:
    print(f"\n{'=' * 70}\n{path.name}\n{'=' * 70}")

    last_state: dict[str, dict] = {}
    society_of: dict[str, str] = {}
    checkpoints: dict[int, dict[str, float]] = {}

    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            aid = e["agent_id"]
            last_state[aid] = e
            if e.get("society"):
                society_of[aid] = e["society"]
            inv = e.get("state_after", {}).get("inventory", {})
            wealth = sum(v for v in inv.values() if isinstance(v, (int, float)))
            cp = e["tick"] // CHECKPOINT_SIZE
            checkpoints.setdefault(cp, {})[aid] = wealth

    # --- overall + per-society final Gini ---
    final_wealth = {a: sum(v for v in s.get("state_after", {}).get("inventory", {}).values() if isinstance(v, (int, float)))
                     for a, s in last_state.items()}
    all_w = np.array(list(final_wealth.values()))
    print(f"final Gini coefficient (all {len(all_w)} agents): {gini(all_w):.3f}")

    by_society: dict[str, list[float]] = {}
    for a, w in final_wealth.items():
        soc = society_of.get(a)
        if soc:
            by_society.setdefault(soc, []).append(w)
    for soc in sorted(by_society):
        w = np.array(by_society[soc])
        print(f"  {soc}: Gini={gini(w):.3f} (n={len(w)}, mean wealth={w.mean():.1f}, max={w.max():.1f})")

    # --- inequality over time ---
    print("\nGini over time (per 10,000-tick checkpoint, using last-known wealth in that window):")
    for cp in sorted(checkpoints):
        w = np.array(list(checkpoints[cp].values()))
        print(f"  tick ~{cp*CHECKPOINT_SIZE:>7}: Gini={gini(w):.3f} (n={len(w)})")

    # --- does inequality predict survival? ---
    agents = list(final_wealth.keys())
    wealths = np.array([final_wealth[a] for a in agents])
    survived = np.array([1 if last_state[a].get("state_after", {}).get("alive", True) else 0 for a in agents])
    if np.std(wealths) > 0 and np.std(survived) > 0:
        r, p = stats.spearmanr(wealths, survived)
        print(f"\nfinal wealth vs survival: rho={r:+.3f} (p={p:.3g})")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python3 analyze_inequality.py run1.jsonl [run2.jsonl ...]")
        sys.exit(1)
    for p in sys.argv[1:]:
        analyze(Path(p))
