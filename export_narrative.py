"""Narrative exporter (Phase 3): filters a run's log down to what's actually
worth reading and renders it as a markdown story. Read-only, same as every
exporter - never imports tick.py/decide.py/actions.py, never runs a sim.

Deliberately excludes routine crowd gather/trade/rest: at 40 agents taking
thousands of actions, including it would bury the signal, not add spectacle.
Included: every lead-tier action (there are only a couple of leads, so this
stays naturally sparse) and every DEATH regardless of tier (the one crowd
event that's dramatically meaningful). Template-based text from the log's own
fields - no LLM call, so no risk of the blocking-call problem from Phase 2
for something that doesn't need it.

    python export_narrative.py --log-path logs/batch/seed7.jsonl --out story.md
"""

from __future__ import annotations

import argparse
import json


def describe(e: dict) -> str:
    tick = e["tick"]
    agent = e["agent_id"]
    action = e["action"]
    target = e["target"]
    success = e["success"]

    if action == "DEATH":
        cause = "hunger" if e["state_before"].get("hunger", 0) >= 99 else "exhaustion"
        return f"**Tick {tick}** — {agent} dies of {cause}."

    if not success:
        return None  # a lead's failed attempt isn't worth narrating, only what actually happened

    if action == "TRADE":
        delta = e["delta"]
        gave = next((k.split(".")[-1] for k, v in delta.items() if k.startswith("inventory.") and v < 0), "something")
        got = next((k.split(".")[-1] for k, v in delta.items() if k.startswith("inventory.") and v > 0), "something")
        return f"**Tick {tick}** — {agent} trades {gave} for {got} with {target}."

    if action == "CRAFT":
        return f"**Tick {tick}** — {agent} crafts a tool."

    if action == "SIGNAL":
        # for SIGNAL, `target` holds the signal kind itself (e.g. "order:wood",
        # "scarce:ore") - not a node id, per resolve_signal in actions.py
        location = e["state_after"]["location"]
        kind = target or ""
        if kind.startswith("order:"):
            return f"**Tick {tick}** — {agent} issues a standing order for {kind.split(':', 1)[1]} at {location}."
        return f"**Tick {tick}** — {agent} signals {kind} at {location}."

    if action == "MOVE":
        return f"**Tick {tick}** — {agent} travels to {target}."

    if action == "GATHER":
        return f"**Tick {tick}** — {agent} gathers resources at {target}."

    if action == "CONSUME":
        return f"**Tick {tick}** — {agent} eats."

    if action == "REST":
        return f"**Tick {tick}** — {agent} rests."

    return f"**Tick {tick}** — {agent} performs {action}."


def export(log_path: str, out_path: str, title: str) -> int:
    lines = [f"# {title}", ""]
    count = 0
    with open(log_path) as f:
        for raw_line in f:
            e = json.loads(raw_line)
            worth_telling = e["action"] == "DEATH" or e["tier"] == "lead"
            if not worth_telling:
                continue
            text = describe(e)
            if text is None:
                continue
            lines.append(text)
            count += 1
    with open(out_path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return count


def main() -> None:
    p = argparse.ArgumentParser(description="seam - narrative exporter")
    p.add_argument("--log-path", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--title", default="The Chronicle of Seam")
    args = p.parse_args()

    count = export(args.log_path, args.out, args.title)
    print(f"wrote {count} narrative lines to {args.out}")


if __name__ == "__main__":
    main()
