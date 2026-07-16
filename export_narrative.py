"""Narrative exporter (Phase 3, real scenes added Phase 5): filters a run's
log down to what's actually worth reading and renders it as a markdown
story. Read-only, same as every exporter - never imports
tick.py/decide.py/actions.py, never runs a sim.

Deliberately excludes routine crowd gather/trade/rest: at 40 agents taking
thousands of actions, including it would bury the signal, not add spectacle.
Included: every lead-tier action (there are only a couple of leads, so this
stays naturally sparse) and every DEATH regardless of tier (the one crowd
event that's dramatically meaningful). Template-based text from the log's own
fields - no LLM call, so no risk of the blocking-call problem from Phase 2
for something that doesn't need it.

In Postgres mode (v2 runs only - a v1 JSONL log has no narrative_scenes
table), the real LLM-authored scenes from Phase 4's sidecar are merged in
at their actual tick position, set off from the templated event lines so
it's clear which is which. This is a genuine upgrade over v1, not a
re-implementation: v1 had to synthesize prose from raw log lines because no
real narrative existed yet.

    python export_narrative.py --log-path logs/batch/seed7.jsonl --out story.md
    python export_narrative.py --postgres-url "dbname=seam" --run-id run-123 --out story.md
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


def read_events_from_jsonl(log_path: str):
    with open(log_path) as f:
        for line in f:
            yield json.loads(line)


def read_events_from_postgres(postgres_url: str, run_id: str):
    import psycopg2
    import psycopg2.extras

    conn = psycopg2.connect(postgres_url)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT tick, agent_id, tier, action, target, success, state_before, state_after, delta "
                "FROM events WHERE run_id = %s ORDER BY tick",
                (run_id,),
            )
            for row in cur:
                yield dict(row)
    finally:
        conn.close()


def read_scenes_from_postgres(postgres_url: str, run_id: str) -> list[tuple[int, str]]:
    import psycopg2

    conn = psycopg2.connect(postgres_url)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT tick, text FROM narrative_scenes WHERE run_id = %s ORDER BY tick", (run_id,))
            return [(tick, text) for tick, text in cur]
    finally:
        conn.close()


def export(events_source, scenes: list[tuple[int, str]], out_path: str, title: str) -> int:
    # Merge chronologically: at a shared tick, the scene reads as a
    # reflection on what just happened, so it goes after the event lines.
    entries: list[tuple[int, int, str]] = []  # (tick, sort_priority, line)
    count = 0
    for e in events_source:
        worth_telling = e["action"] == "DEATH" or e["tier"] == "lead"
        if not worth_telling:
            continue
        text = describe(e)
        if text is None:
            continue
        entries.append((e["tick"], 0, text))
        count += 1
    for tick, text in scenes:
        entries.append((tick, 1, f"> *{text}*"))
        count += 1

    entries.sort(key=lambda t: (t[0], t[1]))
    lines = [f"# {title}", ""] + [line for _, _, line in entries]
    with open(out_path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return count


def main() -> None:
    p = argparse.ArgumentParser(description="seam - narrative exporter")
    p.add_argument("--log-path", default=None, help="v1-style JSONL log")
    p.add_argument("--postgres-url", default=None, help="v2 alternative to --log-path, e.g. 'dbname=seam'")
    p.add_argument("--run-id", default=None, help="required with --postgres-url")
    p.add_argument("--out", required=True)
    p.add_argument("--title", default="The Chronicle of Seam")
    args = p.parse_args()

    if bool(args.log_path) == bool(args.postgres_url):
        p.error("pass exactly one of --log-path or --postgres-url")
    if args.postgres_url and not args.run_id:
        p.error("--postgres-url requires --run-id")

    if args.log_path:
        events = read_events_from_jsonl(args.log_path)
        scenes = []
    else:
        events = read_events_from_postgres(args.postgres_url, args.run_id)
        scenes = read_scenes_from_postgres(args.postgres_url, args.run_id)

    count = export(events, scenes, args.out, args.title)
    print(f"wrote {count} narrative lines to {args.out} ({len(scenes)} of them real authored scenes)")


if __name__ == "__main__":
    main()
