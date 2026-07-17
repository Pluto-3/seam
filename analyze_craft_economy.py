"""Angle 4 of ANALYSIS.md: the craft/tool economy - untouched all project.

Every analysis this whole session has been trade- and death-centric.
CRAFT actions (raw resources -> tools) and tool_durability have never
been looked at once. Does tool ownership correlate with survival or
gather efficiency?

Usage: python3 analyze_craft_economy.py run.jsonl [run2.jsonl ...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from scipy import stats


def analyze(path: Path) -> None:
    print(f"\n{'=' * 70}\n{path.name}\n{'=' * 70}")

    craft_attempts = 0
    craft_successes = 0
    last_state: dict[str, dict] = {}
    gather_by_tool: dict[bool, list[int]] = {True: [0, 0], False: [0, 0]}  # has_tool -> [attempts, successes]

    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            last_state[e["agent_id"]] = e

            if e["action"] == "CRAFT":
                craft_attempts += 1
                if e["success"]:
                    craft_successes += 1

            if e["action"] == "GATHER":
                has_tool = (e.get("state_before", {}).get("tool_durability", 0) or 0) > 0
                gather_by_tool[has_tool][0] += 1
                if e["success"]:
                    gather_by_tool[has_tool][1] += 1

    print(f"CRAFT attempts: {craft_attempts}, successful: {craft_successes} ({craft_successes/craft_attempts*100 if craft_attempts else 0:.1f}%)")

    for has_tool, (att, ok) in gather_by_tool.items():
        label = "WITH a durable tool" if has_tool else "without a tool"
        print(f"gather success rate {label}: {ok}/{att} ({ok/att*100 if att else 0:.1f}%)")

    # tool ownership at end of run vs survival
    agents = list(last_state.keys())
    has_tool_final = np.array([1 if (last_state[a].get("state_after", {}).get("tool_durability", 0) or 0) > 0 else 0 for a in agents])
    survived = np.array([1 if last_state[a].get("state_after", {}).get("alive", True) else 0 for a in agents])
    owners = int(has_tool_final.sum())
    print(f"\n{owners}/{len(agents)} agents ended the run holding a durable tool ({owners/len(agents)*100:.1f}%)")
    if np.std(has_tool_final) > 0 and np.std(survived) > 0:
        r, p = stats.spearmanr(has_tool_final, survived)
        print(f"final tool ownership vs survival: rho={r:+.3f} (p={p:.3g})")
    else:
        print("(no variance in one of the two - correlation undefined, e.g. everyone/no one has a tool or everyone/no one survived)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python3 analyze_craft_economy.py run1.jsonl [run2.jsonl ...]")
        sys.exit(1)
    for p in sys.argv[1:]:
        analyze(Path(p))
