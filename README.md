# seam

A simulated agent economy where trade, specialization, and scarcity emerge from simple rules — and a small cast of LLM-driven agents pursue distinct goals inside that same world, running entirely on your own machine.

Dozens of simple agents gather, trade, and craft resources under real scarcity. A handful of goal-driven agents reason about what to do next using a local language model. You can drop into the world yourself and drive a character directly. Every tick gets logged, and that one log can be read three different ways: as a clean dataset, as a report on which behaviors actually worked, or as a readable story of what happened.

## Proven, not assumed

Every claim below is backed by a measured result, not a single example run:

- **Trade emerges from scarcity alone.** A 20-seed paired comparison (trade enabled vs. disabled, same seeds, same world) shows agents redistribute resources far more with trade on — a specialization index of 0.49 vs. 0.37, trade winning in 19 of 20 seeds.
- **Goal-driven agents behave differently without being scripted to.** LLM-driven agents pick from the same legal options the rest of the world has — never inventing an action — and different stated goals produce genuinely different behavior: an agent driven to "become the wealthiest trader" trades on nearly every decision; an agent told to "keep the settlement stocked on wood" shows a broader gather/rest/trade mix. Verified across 40 real decisions with zero fallbacks needed.
- **Runs fully locally, with no blocking.** The reasoning layer uses a local model (Ollama) — no API key, no cloud dependency — and is architected so a slow or unresponsive model can never freeze the simulation, verified by deliberately hanging the model call and confirming the app kept running exactly on schedule.
- **A population-collapse bug affecting roughly 1 world in 20 was root-caused, fixed, and confirmed at full scale** — not just on the seed where it was found. Final result: 40 out of 40 agents survive in all 20 test seeds, zero regressions.

Full build and debugging history — including two regressions that were caught before shipping, not after — is in [`LOG.md`](LOG.md).

## Architecture

Three tiers of agents share one simulated world:

- **Crowd** — dozens of simple agents, each scored by a shared utility function over a small action set (gather, trade, rest, craft, consume, move, signal).
- **Leads** — a small cast with a real goal and personality, driven by a local LLM that picks from the same legal options the crowd has. Any parse failure or model error falls back to the crowd's own scoring, so a bad response degrades a lead to crowd-like behavior instead of breaking it.
- **Hatch** — a player-controllable character sharing the same world, possess-and-release at will.

Every tick is written to one log. Three exporters read that same log three different ways, none of them touching the simulation itself:

- `export_data.py` — a clean, versioned dataset (manifest + flattened CSV).
- `export_strategy.py` — which agents actually did well and what distinguished them, or a before/after comparison between two runs.
- `export_narrative.py` — a readable markdown account of what the leads did and who died.

## Quick start

```bash
# headless simulation, no dependencies beyond the standard library
python run.py --agents 40 --nodes 15 --ticks 3000 --seed 42

# live view (needs pygame; leads need Ollama running locally)
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python watch.py --seed 42

# read a run's log three different ways
python export_data.py --log-path logs/run.jsonl --out exports/run1
python export_strategy.py single --log-path logs/run.jsonl
python export_narrative.py --log-path logs/run.jsonl --out story.md
```

## Status

**v1** — the concept is proven: scarcity produces real trade, goal-driven agents behave differently without being scripted to, and the tooling to extract value from a run (dataset, strategy report, narrative) all works, verified at scale rather than assumed. See [`DESIGN.md`](DESIGN.md) for the design decisions and reasoning, and [`LOG.md`](LOG.md) for the full history of what was tried, what broke, and how it was fixed.

## Tech

Python (standard library only for the simulation core — no dependencies to run a headless simulation at all), pygame for the live view, Ollama for local LLM inference. No API keys required anywhere.
