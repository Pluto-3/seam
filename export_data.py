"""Data exporter (Phase 3, Postgres support added Phase 5): turns a run's
event log into a self-contained, versioned dataset - a manifest plus flat
CSVs, since flat tabular data is what external tools (pandas, spreadsheets)
actually want, not nested JSON.

Read-only either way: reads a v1 JSONL log (run.py/watch.py) or queries a v2
`serve` run's Postgres tables (`--postgres-url`/`--run-id`). Never imports
tick.py, decide.py, or actions.py, and never runs a simulation.

    python export_data.py --log-path logs/batch/seed1.jsonl --out exports/seed1
    python export_data.py --postgres-url "dbname=seam" --run-id run-123 --out exports/run-123

Postgres mode also exports the richer v2 tables JSONL never had - lead
memory over time and settlement health over time - as their own CSVs.
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


def read_entries_from_jsonl(log_path: str):
    with open(log_path) as f:
        for line in f:
            yield json.loads(line)


def read_entries_from_postgres(postgres_url: str, run_id: str):
    import psycopg2
    import psycopg2.extras

    conn = psycopg2.connect(postgres_url)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT tick, agent_id, tier, action, target, success, state_after, delta "
                "FROM events WHERE run_id = %s ORDER BY tick",
                (run_id,),
            )
            for row in cur:
                yield dict(row)
    finally:
        conn.close()


def export_postgres_extras(postgres_url: str, run_id: str, out_dir: str) -> dict:
    """The tables JSONL never had: lead memory and settlement health over
    time. Only reachable via Postgres mode - this is genuinely new data,
    not a re-export of anything v1 could produce."""
    import psycopg2
    import psycopg2.extras

    counts = {}
    conn = psycopg2.connect(postgres_url)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT tick, lead_id, memory_summary, caution_bias, trade_success_ratio, hunger_scares_witnessed, ts "
                "FROM lead_memory_snapshots WHERE run_id = %s ORDER BY tick",
                (run_id,),
            )
            rows = [dict(r) for r in cur]
            if rows:
                path = os.path.join(out_dir, "lead_memory.csv")
                with open(path, "w", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                    writer.writeheader()
                    writer.writerows(rows)
            counts["lead_memory_rows"] = len(rows)

            cur.execute(
                "SELECT tick, node, population_alive, roster_size, avg_energy, avg_hunger, total_food_held, ts "
                "FROM settlement_snapshots WHERE run_id = %s ORDER BY tick",
                (run_id,),
            )
            rows = [dict(r) for r in cur]
            if rows:
                path = os.path.join(out_dir, "settlement_health.csv")
                with open(path, "w", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                    writer.writeheader()
                    writer.writerows(rows)
            counts["settlement_snapshot_rows"] = len(rows)
    finally:
        conn.close()
    return counts


def export(entries_source, source_label: str, out_dir: str, seed, num_agents, num_nodes,
           postgres_url: str = None, run_id: str = None) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    csv_path = os.path.join(out_dir, "trajectories.csv")
    manifest_path = os.path.join(out_dir, "manifest.json")

    min_tick, max_tick, num_entries = None, None, 0
    agent_ids_by_tier: dict[str, set] = {}
    action_counts: dict[str, int] = {}

    with open(csv_path, "w", newline="") as f_out:
        writer = csv.DictWriter(f_out, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for e in entries_source:
            num_entries += 1
            tick = e["tick"]
            min_tick = tick if min_tick is None else min(min_tick, tick)
            max_tick = tick if max_tick is None else max(max_tick, tick)
            agent_ids_by_tier.setdefault(e["tier"], set()).add(e["agent_id"])
            action_counts[e["action"]] = action_counts.get(e["action"], 0) + 1
            writer.writerow(flatten_entry(e))

    manifest = {
        "source": source_label,
        "export_timestamp": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_commit_hash(),
        "tick_range": [min_tick, max_tick],
        "num_log_entries": num_entries,
        "agents_by_tier": {tier: len(ids) for tier, ids in agent_ids_by_tier.items()},
        "action_counts": action_counts,
        "requested_run_params": {"seed": seed, "num_agents": num_agents, "num_nodes": num_nodes},
    }

    if postgres_url and run_id:
        manifest["postgres_extras"] = export_postgres_extras(postgres_url, run_id, out_dir)

    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    return manifest


def main() -> None:
    p = argparse.ArgumentParser(description="seam - data exporter")
    p.add_argument("--log-path", default=None, help="v1-style JSONL log")
    p.add_argument("--postgres-url", default=None, help="v2 alternative to --log-path, e.g. 'dbname=seam'")
    p.add_argument("--run-id", default=None, help="required with --postgres-url")
    p.add_argument("--out", required=True, help="output directory")
    p.add_argument("--seed", type=int, default=None, help="original run's seed, for provenance only")
    p.add_argument("--agents", type=int, default=None, help="original run's agent count, for provenance only")
    p.add_argument("--nodes", type=int, default=None, help="original run's node count, for provenance only")
    args = p.parse_args()

    if bool(args.log_path) == bool(args.postgres_url):
        p.error("pass exactly one of --log-path or --postgres-url")
    if args.postgres_url and not args.run_id:
        p.error("--postgres-url requires --run-id")

    if args.log_path:
        entries = read_entries_from_jsonl(args.log_path)
        source_label = os.path.abspath(args.log_path)
    else:
        entries = read_entries_from_postgres(args.postgres_url, args.run_id)
        source_label = f"postgres:{args.run_id}"

    manifest = export(entries, source_label, args.out, args.seed, args.agents, args.nodes,
                       postgres_url=args.postgres_url, run_id=args.run_id)
    print(f"exported {manifest['num_log_entries']} entries (ticks {manifest['tick_range'][0]}-"
          f"{manifest['tick_range'][1]}) to {args.out}/")
    print(f"agents by tier: {manifest['agents_by_tier']}")
    print(f"action counts: {manifest['action_counts']}")
    if "postgres_extras" in manifest:
        print(f"postgres extras: {manifest['postgres_extras']}")


if __name__ == "__main__":
    main()
