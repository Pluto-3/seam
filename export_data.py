"""Data exporter (Phase 3): turns a run's raw JSONL log into a self-contained,
versioned dataset - a manifest plus a flat CSV, since flat tabular data is what
external tools (pandas, spreadsheets) actually want, not nested JSON.

Read-only: only ever reads a log file already produced by run.py/watch.py.
Never imports tick.py, decide.py, or actions.py, and never runs a simulation.

    python export_data.py --log-path logs/batch/seed1.jsonl --out exports/seed1
    python export_data.py --log-path logs/batch/seed1.jsonl --out exports/seed1 --seed 1 --agents 40 --nodes 15
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
from datetime import datetime, timezone

RAW_RESOURCES = ("ore", "food", "wood")

CSV_FIELDS = [
    "tick", "agent_id", "tier", "action", "target", "success",
    "energy", "hunger", "alive", "tool_durability",
    "inventory_ore", "inventory_food", "inventory_wood",
    "delta_energy", "delta_hunger", "delta_tool_durability",
    "delta_inventory_ore", "delta_inventory_food", "delta_inventory_wood",
    "delta_location", "delta_alive",
]


def git_commit_hash() -> str:
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5)
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except (subprocess.SubprocessError, OSError):
        return "unknown"


def flatten_entry(e: dict) -> dict:
    after = e["state_after"]
    delta = e["delta"]
    inv = after.get("inventory", {})
    row = {
        "tick": e["tick"], "agent_id": e["agent_id"], "tier": e["tier"],
        "action": e["action"], "target": e["target"], "success": e["success"],
        "energy": after.get("energy"), "hunger": after.get("hunger"),
        "alive": after.get("alive"), "tool_durability": after.get("tool_durability"),
    }
    for res in RAW_RESOURCES:
        row[f"inventory_{res}"] = inv.get(res, 0.0)
        row[f"delta_inventory_{res}"] = delta.get(f"inventory.{res}", 0.0)
    row["delta_energy"] = delta.get("energy", 0.0)
    row["delta_hunger"] = delta.get("hunger", 0.0)
    row["delta_tool_durability"] = delta.get("tool_durability", 0.0)
    row["delta_location"] = delta.get("location", "")
    row["delta_alive"] = delta.get("alive", "")
    return row


def export(log_path: str, out_dir: str, seed, num_agents, num_nodes) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    csv_path = os.path.join(out_dir, "trajectories.csv")
    manifest_path = os.path.join(out_dir, "manifest.json")

    min_tick, max_tick, num_entries = None, None, 0
    agent_ids_by_tier: dict[str, set] = {}
    action_counts: dict[str, int] = {}

    with open(log_path) as f_in, open(csv_path, "w", newline="") as f_out:
        writer = csv.DictWriter(f_out, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for line in f_in:
            e = json.loads(line)
            num_entries += 1
            tick = e["tick"]
            min_tick = tick if min_tick is None else min(min_tick, tick)
            max_tick = tick if max_tick is None else max(max_tick, tick)
            agent_ids_by_tier.setdefault(e["tier"], set()).add(e["agent_id"])
            action_counts[e["action"]] = action_counts.get(e["action"], 0) + 1
            writer.writerow(flatten_entry(e))

    manifest = {
        "source_log_path": os.path.abspath(log_path),
        "export_timestamp": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_commit_hash(),
        "tick_range": [min_tick, max_tick],
        "num_log_entries": num_entries,
        "agents_by_tier": {tier: len(ids) for tier, ids in agent_ids_by_tier.items()},
        "action_counts": action_counts,
        "requested_run_params": {"seed": seed, "num_agents": num_agents, "num_nodes": num_nodes},
    }
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    return manifest


def main() -> None:
    p = argparse.ArgumentParser(description="seam - data exporter")
    p.add_argument("--log-path", required=True)
    p.add_argument("--out", required=True, help="output directory")
    p.add_argument("--seed", type=int, default=None, help="original run's seed, for provenance only")
    p.add_argument("--agents", type=int, default=None, help="original run's agent count, for provenance only")
    p.add_argument("--nodes", type=int, default=None, help="original run's node count, for provenance only")
    args = p.parse_args()

    manifest = export(args.log_path, args.out, args.seed, args.agents, args.nodes)
    print(f"exported {manifest['num_log_entries']} entries (ticks {manifest['tick_range'][0]}-"
          f"{manifest['tick_range'][1]}) to {args.out}/")
    print(f"agents by tier: {manifest['agents_by_tier']}")
    print(f"action counts: {manifest['action_counts']}")


if __name__ == "__main__":
    main()
