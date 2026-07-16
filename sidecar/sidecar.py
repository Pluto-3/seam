"""LLM orchestration sidecar (Phase 2-4) - talks to the Rust `serve` service
over HTTP instead of the simulation living in the same process, the way v1's
leads.py did. Handles lead decisions + memory (Phase 2) and the periodic
narrative scene (Phase 4).

Same non-blocking shape as v1 (leads.py + watch.py's ThreadPoolExecutor):
every lead decision runs on a background thread; the main loop never waits
on Ollama. A lead with no fresh decision posted just keeps running on the
Rust service's own crowd-style autopilot for that tick - never broken,
worst case it behaves like a crowd agent, same guarantee v1 made.

    python3 sidecar.py --service http://localhost:7878

Requires: stdlib only. No dependency beyond what's already on the machine
for v1 (Ollama running locally).
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import threading
import time
import urllib.error
import urllib.request
from typing import Optional

OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "llama3.2:3b"
REQUEST_TIMEOUT = 15.0  # seconds

LEAD_DECISION_INTERVAL_SECONDS = 3.0   # real-time equivalent of v1's 20-tick interval
MEMORY_SUMMARY_INTERVAL_SECONDS = 30.0  # much less frequent - this is the "periodic" self-summary
NARRATIVE_INTERVAL_SECONDS = 90.0  # slower still - a scene every so often, not a play-by-play


def query_ollama(prompt: str, model: str = DEFAULT_MODEL, timeout: float = REQUEST_TIMEOUT) -> Optional[str]:
    payload = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return body.get("response")
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None


def _parse_choice(response: Optional[str], n: int) -> Optional[int]:
    if not response:
        return None
    for token in response.strip().split():
        digits = "".join(c for c in token if c.isdigit())
        if digits:
            choice = int(digits)
            if 1 <= choice <= n:
                return choice - 1
    return None


class DecisionLog:
    """Thread-safe append-only JSONL of every decision/summary attempt - what
    was asked, whether the model answered usefully, what got posted. This is
    debug/analysis data, not something the sim depends on; safe to omit
    (pass log_path=None) with zero behavior change elsewhere."""

    def __init__(self, path: Optional[str]):
        self._lock = threading.Lock()
        self._file = open(path, "a") if path else None

    def record(self, **fields) -> None:
        if self._file is None:
            return
        fields["ts"] = time.time()
        line = json.dumps(fields)
        with self._lock:
            self._file.write(line + "\n")
            self._file.flush()


class ServiceClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def _get(self, path: str) -> Optional[object]:
        try:
            with urllib.request.urlopen(f"{self.base_url}{path}", timeout=5.0) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            return None

    def _post(self, path: str, payload: object) -> bool:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}{path}", data=data, headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5.0):
                return True
        except (urllib.error.URLError, TimeoutError, OSError):
            return False

    def get_agents(self) -> list[dict]:
        return self._get("/agents") or []

    def get_leads(self) -> list[dict]:
        return self._get("/leads") or []

    def get_candidates(self, lead_id: str) -> list[dict]:
        return self._get(f"/leads/{lead_id}/candidates") or []

    def post_intent(self, lead_id: str, intent: dict) -> bool:
        return self._post(f"/leads/{lead_id}/intent", intent)

    def post_memory(self, lead_id: str, summary: str) -> bool:
        return self._post(f"/leads/{lead_id}/memory", {"memory_summary": summary})

    def post_identities(self, updates: list[dict]) -> bool:
        return self._post("/agents/identities", updates)

    def get_settlement(self) -> Optional[dict]:
        return self._get("/settlement")

    def get_narrative(self) -> list[dict]:
        return self._get("/narrative") or []

    def post_narrative(self, text: str) -> bool:
        return self._post("/narrative", {"text": text})


def build_decision_prompt(lead: dict, candidates: list[dict]) -> str:
    lines = [
        f"You are an agent in a small simulated economy. Your goal: {lead['goal']}. "
        f"Your personality: {lead['personality']}.",
        f"Current state: energy {lead['energy']:.0f}/100, hunger {lead['hunger']:.0f}/100, "
        f"holding {lead['inventory']}.",
    ]
    if lead.get("memory_summary"):
        lines.append(f"Your own recent recollection: {lead['memory_summary']}")
    lines.append("Your available actions right now:")
    for c in candidates:
        lines.append(f"{c['index']}. {c['description']}")
    lines.append(f"Reply with ONLY the number (1-{len(candidates)}) of the action you choose. No other text.")
    return "\n".join(lines)


def build_memory_prompt(lead: dict) -> str:
    ratio = lead.get("trade_success_ratio")
    ratio_desc = "no recent trade attempts" if ratio is None else f"{ratio * 100:.0f}% of recent trade attempts succeeded"
    return (
        f"You are an agent in a simulated economy. Your goal: {lead['goal']}. "
        f"Your personality: {lead['personality']}.\n"
        f"Recently: {ratio_desc}. You've had {lead['hunger_scares_witnessed']} close calls with hunger this run.\n"
        "Write ONE short first-person sentence reflecting on how things have been going for you. "
        "No preamble, no quotes, just the sentence."
    )


def decide_for_lead(client: ServiceClient, lead_id: str, model: str, log: DecisionLog) -> None:
    leads = {l["id"]: l for l in client.get_leads()}
    lead = leads.get(lead_id)
    if lead is None or not lead["alive"]:
        return
    candidates = client.get_candidates(lead_id)
    if not candidates:
        return

    response = query_ollama(build_decision_prompt(lead, candidates), model=model)
    choice_index = _parse_choice(response, len(candidates))
    if choice_index is None:
        # Model failed to answer usefully in time - post nothing. The lead
        # just runs on the Rust service's own crowd-style autopilot this
        # tick, exactly the same fallback guarantee v1 made.
        log.record(kind="decision", lead_id=lead_id, llm_answered=False,
                   raw_response=response, num_candidates=len(candidates))
        return
    chosen = candidates[choice_index]
    client.post_intent(lead_id, chosen["intent"])
    log.record(kind="decision", lead_id=lead_id, llm_answered=True,
               chosen_action=chosen["intent"]["action"], chosen_description=chosen["description"],
               num_candidates=len(candidates))


def summarize_for_lead(client: ServiceClient, lead_id: str, model: str, log: DecisionLog) -> None:
    leads = {l["id"]: l for l in client.get_leads()}
    lead = leads.get(lead_id)
    if lead is None or not lead["alive"]:
        return
    response = query_ollama(build_memory_prompt(lead), model=model)
    if not response:
        log.record(kind="memory", lead_id=lead_id, llm_answered=False)
        return
    summary = response.strip().splitlines()[0][:280]
    client.post_memory(lead_id, summary)
    log.record(kind="memory", lead_id=lead_id, llm_answered=True, summary=summary,
               trade_success_ratio=lead.get("trade_success_ratio"),
               hunger_scares_witnessed=lead.get("hunger_scares_witnessed"))


def build_narrative_prompt(leads: list[dict], settlement: dict, previous_scene: str) -> str:
    lead_lines = []
    for l in leads:
        if not l["alive"]:
            lead_lines.append(f"- {l.get('display_name') or l['id']} has died.")
            continue
        note = f' They recently said: "{l["memory_summary"]}"' if l.get("memory_summary") else ""
        # location is spelled out as "currently located at node X" rather than
        # a bare "at X" - a small model reading "...(become the wealthiest
        # trader), at n3..." kept misreading the node id as a wealth/status
        # number, since it landed right next to wealth-flavored goal text.
        # Caught by actually reading the narrative output, not assumed.
        lead_lines.append(
            f"- {l.get('display_name') or l['id']}: goal is to {l['goal']}. "
            f"Currently located at node {l['location']} (a place, not an amount). "
            f"Energy {l['energy']:.0f}/100, hunger {l['hunger']:.0f}/100.{note}"
        )

    settlement_line = (
        f"The settlement at node {settlement['node']}: {settlement['population_alive']}/{settlement['roster_size']} "
        f"people, average hunger {settlement['avg_hunger']:.0f}, {settlement['total_food_held']:.0f} food on hand."
    )

    context = "\n".join(["Leads:"] + lead_lines + ["", settlement_line])
    continuity = f'\nThe last thing written about this world was: "{previous_scene}"\n' if previous_scene else ""

    return (
        "Write a two-sentence status report on the simulated economy below, using ONLY the "
        "facts given. Do not invent people, objects, professions, weather, or actions that "
        "aren't stated. Do not describe anyone gathering, cooking, or crafting unless it's "
        "in the data. Node ids (like n0, n3) are places, never amounts or scores - never "
        "describe someone's wealth, rank, or status using a node id. Just restate what the "
        "numbers and quotes below actually say, in plain prose instead of a list. If nothing "
        "here differs meaningfully from what was last written, say so plainly instead of "
        "repeating the same claim in new words. Present tense, third person, no preamble, "
        "no title.\n\n"
        f"{context}\n{continuity}"
        "Status report:"
    )


def _narrative_signature(leads: list[dict], settlement: dict) -> tuple:
    """A coarse fingerprint of 'is there anything new to say' - rounded so
    routine per-tick noise doesn't count as change, only asking Ollama to
    write something when the picture has actually shifted."""
    lead_sig = tuple(
        (l["id"], l["alive"], l["location"], round(l["energy"] / 10), round(l["hunger"] / 10), l.get("memory_summary", ""))
        for l in leads
    )
    settlement_sig = (
        settlement["population_alive"], round(settlement["avg_hunger"] / 10), round(settlement["total_food_held"] / 20),
    )
    return (lead_sig, settlement_sig)


def write_narrative_scene(client: ServiceClient, model: str, log: DecisionLog, previous: dict) -> None:
    leads = client.get_leads()
    settlement = client.get_settlement()
    if not leads or settlement is None:
        return

    signature = _narrative_signature(leads, settlement)
    if signature == previous.get("signature"):
        # Nothing meaningfully different since the last scene - skip the
        # call entirely rather than pay for (and inflict) another
        # near-identical restatement of the same static fact.
        log.record(kind="narrative", llm_answered=False, skipped_unchanged=True)
        return

    response = query_ollama(build_narrative_prompt(leads, settlement, previous.get("text", "")), model=model)
    if not response:
        log.record(kind="narrative", llm_answered=False)
        return
    scene = " ".join(response.strip().split())[:500]
    client.post_narrative(scene)
    previous["signature"] = signature
    previous["text"] = scene
    log.record(kind="narrative", llm_answered=True, scene=scene)


CROWD_NAMING_BATCH_SIZE = 10  # one Ollama call per batch, not per agent - cheap flavor, not per-agent cost


def _parse_identity_lines(response: Optional[str], ids: list[str]) -> list[dict]:
    """Parses 'id: Name - blurb' lines, one per agent. Permissive: any line
    that doesn't parse cleanly is just skipped, not a failure for the batch -
    a partial set of crowd names is fine, this is cosmetic flavor, not a
    mechanic anything depends on."""
    if not response:
        return []
    wanted = set(ids)
    updates = []
    for line in response.strip().splitlines():
        if ":" not in line:
            continue
        agent_id, rest = line.split(":", 1)
        agent_id = agent_id.strip()
        if agent_id not in wanted:
            continue
        rest = rest.strip()
        if "-" in rest:
            name, blurb = rest.split("-", 1)
        elif "—" in rest:
            name, blurb = rest.split("—", 1)
        else:
            name, blurb = rest, ""
        updates.append({"id": agent_id, "display_name": name.strip() or None, "blurb": blurb.strip() or None})
    return updates


def assign_crowd_identities(client: ServiceClient, model: str) -> None:
    """One-time, batched at startup - a name and one-line identity for every
    crowd agent that doesn't already have one, a handful of Ollama calls
    total rather than one per agent."""
    agents = client.get_agents()
    unnamed = [a["id"] for a in agents if a["tier"] == "crowd" and not a.get("display_name")]
    for i in range(0, len(unnamed), CROWD_NAMING_BATCH_SIZE):
        batch = unnamed[i : i + CROWD_NAMING_BATCH_SIZE]
        prompt = (
            "Invent a short first name and a punchy one-line identity for each of these "
            "characters in a small simulated trading economy. Reply with exactly one line "
            "per id, in this exact format, no other text:\n"
            + "\n".join(f"{aid}: <Name> - <one-line identity>" for aid in batch)
        )
        response = query_ollama(prompt, model=model)
        updates = _parse_identity_lines(response, batch)
        if updates:
            client.post_identities(updates)


def assign_lead_identities(client: ServiceClient, model: str) -> None:
    """Leads already surface goal/personality separately in the viewer, so
    this is just a fitting first name, not a full identity - one small
    batched call. Fixes a real gap: the crowd got named at startup from the
    start, leads never did, even though Phase 2's design intent covered
    both. Deliberately silly rather than a serious fantasy name - a small
    settlement's over-earnest wealthiest trader having a name like
    "Reginald Sneezeypants III" is funnier than it being self-serious about
    it, and there's no reason a dev tool's names need to be dignified."""
    leads = client.get_leads()
    unnamed = [l for l in leads if not l.get("display_name")]
    if not unnamed:
        return
    prompt = (
        "Invent a ridiculous, absurd Rick-and-Morty-style name for each character below - "
        "deadpan, irreverent, silly, the kind of name that clashes with how self-serious they "
        "are about their goal. Not a normal fantasy name. Reply with exactly one line per id, "
        "in this exact format, no other text:\n"
        + "\n".join(f"{l['id']}: <Name>  (goal: {l['goal']}, personality: {l['personality']})" for l in unnamed)
    )
    response = query_ollama(prompt, model=model)
    if not response:
        return
    wanted = {l["id"] for l in unnamed}
    updates = []
    for line in response.strip().splitlines():
        if ":" not in line:
            continue
        agent_id, rest = line.split(":", 1)
        agent_id = agent_id.strip()
        if agent_id not in wanted:
            continue
        name = rest.split("(")[0].strip()  # drop any echoed goal/personality parenthetical
        if name:
            updates.append({"id": agent_id, "display_name": name})
    if updates:
        client.post_identities(updates)


def main() -> None:
    p = argparse.ArgumentParser(description="seam v2 Phase 2 - LLM orchestration sidecar")
    p.add_argument("--service", default="http://localhost:7878")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--decision-interval", type=float, default=LEAD_DECISION_INTERVAL_SECONDS)
    p.add_argument("--memory-interval", type=float, default=MEMORY_SUMMARY_INTERVAL_SECONDS)
    p.add_argument("--narrative-interval", type=float, default=NARRATIVE_INTERVAL_SECONDS)
    p.add_argument("--log-path", default=None, help="JSONL log of every decision/summary attempt (optional)")
    args = p.parse_args()

    log = DecisionLog(args.log_path)
    client = ServiceClient(args.service)
    leads = client.get_leads()
    if not leads:
        print(f"no leads found at {args.service}/leads - is `serve` running?")
        return
    lead_ids = [l["id"] for l in leads]
    print(f"sidecar watching leads: {lead_ids} (model={args.model})", flush=True)

    print("assigning crowd + lead identities (one-time, batched)...", flush=True)
    assign_crowd_identities(client, args.model)
    assign_lead_identities(client, args.model)
    print("done", flush=True)

    # Continuity across sidecar restarts: pick up the last scene already
    # posted, if any, rather than starting the story over from nothing.
    existing_narrative = client.get_narrative()
    previous_scene = {"text": existing_narrative[-1]["text"] if existing_narrative else ""}

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(lead_ids)) * 2 + 1)
    decision_futures: dict[str, concurrent.futures.Future] = {}
    memory_futures: dict[str, concurrent.futures.Future] = {}
    narrative_future: Optional[concurrent.futures.Future] = None
    next_decision_due = {lid: 0.0 for lid in lead_ids}
    next_memory_due = {lid: time.monotonic() + args.memory_interval for lid in lead_ids}
    next_narrative_due = time.monotonic() + args.narrative_interval

    try:
        while True:
            now = time.monotonic()

            for lid, fut in list(decision_futures.items()):
                if fut.done():
                    del decision_futures[lid]

            for lid, fut in list(memory_futures.items()):
                if fut.done():
                    del memory_futures[lid]

            if narrative_future is not None and narrative_future.done():
                narrative_future = None

            for lid in lead_ids:
                if now >= next_decision_due[lid] and lid not in decision_futures:
                    decision_futures[lid] = executor.submit(decide_for_lead, client, lid, args.model, log)
                    next_decision_due[lid] = now + args.decision_interval

                if now >= next_memory_due[lid] and lid not in memory_futures:
                    memory_futures[lid] = executor.submit(summarize_for_lead, client, lid, args.model, log)
                    next_memory_due[lid] = now + args.memory_interval

            if now >= next_narrative_due and narrative_future is None:
                narrative_future = executor.submit(write_narrative_scene, client, args.model, log, previous_scene)
                next_narrative_due = now + args.narrative_interval

            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nstopping sidecar")
        executor.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    main()
