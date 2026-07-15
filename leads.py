"""LLM-driven decision source for lead-tier agents. Headless-safe: no pygame import.

Leads never invent an action from scratch - they pick from decide.py's own
generate_candidates(), the exact same legal options a crowd agent would score.
Small local models are unreliable at freeform structured output, so the
model's only job is picking a number from a short list; any parse failure
(timeout, malformed response, out-of-range number) falls back to the same
argmax the crowd already uses. A bad LLM response never breaks a lead - worst
case it behaves like a crowd agent that tick.
"""

from __future__ import annotations

import json
import random
import urllib.error
import urllib.request
from typing import Optional

from agents import AgentState
from decide import Intent, generate_candidates
from world import RAW_RESOURCES, World

OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "llama3.2:3b"
REQUEST_TIMEOUT = 15.0  # seconds
LEAD_DECISION_INTERVAL = 20  # ticks between fresh LLM-driven decisions per lead -
                              # LLM calls are slow relative to a tick, so leads run
                              # on the same autopilot as everyone else in between

LEAD_GOALS = [
    ("become the wealthiest trader in the region", "shrewd and opportunistic"),
    ("keep this settlement well stocked on wood", "cautious and protective"),
    ("out-produce every other agent at your specialty", "competitive and driven"),
]


def spawn_leads(n: int, world: World, rng: random.Random) -> list[AgentState]:
    node_ids = list(world.nodes.keys())
    leads = []
    for i in range(n):
        goal, personality = LEAD_GOALS[i % len(LEAD_GOALS)]
        specialty = RAW_RESOURCES[i % len(RAW_RESOURCES)]
        lead = AgentState(
            id=f"lead{i}",
            tier="lead",
            location=rng.choice(node_ids),
            energy=rng.uniform(70.0, 100.0),
            hunger=rng.uniform(0.0, 30.0),
            specialty=specialty,
            goal=goal,
            personality=personality,
        )
        leads.append(lead)
    return leads


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


def _describe_candidate(index: int, intent: Intent) -> str:
    parts = [intent.action]
    if intent.target:
        parts.append(f"-> {intent.target}")
    if intent.action == "TRADE":
        parts.append(f"(give {intent.give_amt:g} {intent.give}, get {intent.want_amt:g} {intent.want})")
    if intent.action == "SIGNAL":
        parts.append(f"({intent.resource})")
    return f"{index + 1}. {' '.join(parts)}"


def build_prompt(agent: AgentState, candidates: list[tuple[float, Intent]]) -> str:
    lines = [
        f"You are an agent in a small simulated economy. Your goal: {agent.goal}. "
        f"Your personality: {agent.personality}.",
        f"Current state: energy {agent.energy:.0f}/100, hunger {agent.hunger:.0f}/100, "
        f"holding {dict(agent.inventory)}.",
        "Your available actions right now:",
    ]
    for i, (_, intent) in enumerate(candidates):
        lines.append(_describe_candidate(i, intent))
    lines.append(f"Reply with ONLY the number (1-{len(candidates)}) of the action you choose. No other text.")
    return "\n".join(lines)


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


def decide_lead_action(agent: AgentState, world: World, colocated: list[AgentState],
                        tick: int, model: str = DEFAULT_MODEL) -> tuple[Intent, bool]:
    """Returns (intent, was_llm_choice). was_llm_choice=False means the argmax
    fallback fired - the model failed to respond in time, or gave an answer
    that didn't parse to a valid option."""
    candidates = generate_candidates(agent, world, colocated, tick)
    if not candidates:
        return Intent(action="REST"), False

    fallback_intent = max(candidates, key=lambda pair: pair[0])[1]

    response = query_ollama(build_prompt(agent, candidates), model=model)
    choice_index = _parse_choice(response, len(candidates))
    if choice_index is None:
        return fallback_intent, False
    return candidates[choice_index][1], True
