# seam

A simulated agent economy where trade, specialization, and scarcity emerge from simple rules — and a small cast of LLM-driven agents pursue distinct goals inside that same world, running entirely on your own machine.

Dozens of simple agents gather, trade, and craft resources under real scarcity. A handful of goal-driven leads reason about what to do next using a local language model, remembering how things have gone for them. A player-stewarded settlement can be tended or neglected, with a measurable difference either way. The whole thing runs as a persistent service you can watch live, backed by a real Rust core and a proper database — the world keeps existing whether or not anyone's watching.

## Two versions, one proven mechanic

**v1** (Python, tagged [`v1.0.0`](https://github.com/Pluto-3/seam/tree/v1.0.0)) proved the core idea out: scarcity produces real trade, goal-driven agents behave differently without being scripted to, and a run's log can be read three different ways (dataset, strategy report, narrative). It's a complete, working headless/live-view simulation on its own — see the [v1 details](#v1-headless--live-view-python) below.

**v2** (`core-rs/` + `sidecar/`) rebuilds the same proven mechanic as a persistent Rust service with a live web viewer, gives leads real two-layer memory, adds a player-stewarded settlement, generates real narrative, and moves the data layer to Postgres. All six planned phases are done and verified — see [v2 details](#v2-persistent-service-rust--postgres) below.

Both versions are real and runnable. v1 is the smaller, dependency-free way to see the core mechanic; v2 is the actively-developed, richer build.

## Proven, not assumed

Every claim below is backed by a measured result, not a single example run. Full history — including regressions caught before shipping, and results reported at their actual size rather than rounded up — is in [`LOG.md`](LOG.md).

**From v1:**
- **Trade emerges from scarcity alone.** A 20-seed paired comparison (trade enabled vs. disabled, same seeds, same world) shows agents redistribute resources far more with trade on — a specialization index of 0.49 vs. 0.37, trade winning in 19 of 20 seeds.
- **Goal-driven agents behave differently without being scripted to.** LLM-driven agents pick from the same legal options the rest of the world has — never inventing an action — and different stated goals produce genuinely different behavior.
- **A population-collapse bug affecting roughly 1 world in 20 was root-caused, fixed, and confirmed at full scale.** Final result: 40 out of 40 agents survive in all 20 test seeds, zero regressions.

**From v2:**
- **The Rust core reproduces Python's proven results, not just its code.** The same 20-seed trade comparison run against the Rust port lands at a specialization index of 0.491 vs. Python's 0.490. A rare population-collapse pattern found in one Rust seed turned out to affect Python too on a wider seed sample — a real property of the mechanic, not a porting bug.
- **The world persists independent of being watched — proven, not architected-and-assumed.** Connected over WebSocket, disconnected fully, waited 5 real seconds with zero viewers attached, reconnected, and confirmed the tick counter had kept advancing the whole time.
- **Lead memory measurably changes behavior.** A mechanical, no-LLM-required counter (recent trade success, hunger scares) discounts a lead's own risk-taking; the LLM-authored half is a self-summary fed into future decisions. Isolated with a controlled on/off experiment: memory measurably dampens the post-hunger-scare jump in trading (+19.3 percentage points vs. +22.2 without it).
- **A tended settlement genuinely survives longer than a neglected one.** Same seed, same starting state, tending is the only variable: the neglected settlement hit its population floor by tick ~1,028; the tended one didn't reach the same floor until tick ~3,749 — over 3.5x longer.
- **A narrative-generation hallucination was caught and fixed before being called done.** The first version had the model inventing people and events ungrounded in the actual simulation; re-prompted as a grounded status report and re-verified clean.
- **Real gaps found by actually running the thing for real, not just building it.** A structural resource bottleneck was confirmed by direct comparison (15 vs. 25 resource nodes for the same 40 agents: 87% vs. 17% gather-failure rate, 19 vs. 0 deaths). A "standing orders" mechanic was found to be mechanically real but never actually offered to LLM-driven leads as a choice — fixed, then confirmed leads actually started using it in live, unattended play.

## v1: headless / live view (Python)

Three tiers of agents share one simulated world:

- **Crowd** — dozens of simple agents, each scored by a shared utility function over a small action set (gather, trade, rest, craft, consume, move, signal).
- **Leads** — a small cast with a real goal and personality, driven by a local LLM that picks from the same legal options the crowd has. Any parse failure or model error falls back to the crowd's own scoring.
- **Hatch** — a player-controllable character sharing the same world, possess-and-release at will.

Every tick is written to one log. Three exporters read that same log three different ways, none of them touching the simulation itself:

- `export_data.py` — a clean, versioned dataset (manifest + flattened CSV).
- `export_strategy.py` — which agents actually did well and what distinguished them, or a before/after comparison between two runs.
- `export_narrative.py` — a readable markdown account of what the leads did and who died.

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

Design decisions and full reasoning: [`DESIGN.md`](DESIGN.md).

## v2: persistent service (Rust + Postgres)

The same mechanic, rebuilt as something that keeps running whether or not you're looking at it:

- **`core-rs/`** — the simulation core ported to Rust, plus two binaries: `run` (headless, same shape as v1's) and `serve` (the persistent service — ticks in the background, exposes state over REST/WebSocket, serves a live browser viewer at `/`).
- **Leads get real memory** — a mechanical counter that discounts risk-taking after a run of bad luck, plus an LLM-authored self-summary fed into future decisions.
- **A settlement** — one node plus a fixed roster of agents, with health shown as raw numbers (population, hunger, food) rather than an invented score. A player-controlled **hatch** can tend it directly.
- **Real narrative** — a periodic LLM-written scene reading across leads and the settlement, shown live in the viewer alongside the numbers.
- **Postgres data layer** — events, lead memory, narrative scenes, and settlement health all persisted properly, queryable by the same exporters as v1 in an alternate mode.

```bash
# build once
cd core-rs && cargo build --release

# run the persistent service (Postgres optional — omit --postgres-url for a
# quick look with no setup beyond the binary itself)
./target/release/serve --agents 40 --nodes 15 --seed 42 --tick-ms 200 --port 7878

# in another terminal - drives leads' decisions/memory/narrative via Ollama
cd sidecar && python3 sidecar.py --service http://localhost:7878

# open the live viewer
# http://localhost:7878/

# same three exporters, now with an alternate Postgres source
python export_data.py --postgres-url "dbname=seam" --run-id my-run --out exports/my-run
python export_strategy.py single --postgres-url "dbname=seam" --run-id my-run
python export_narrative.py --postgres-url "dbname=seam" --run-id my-run --out story.md
```

Design decisions, phase-by-phase proof conditions, and full reasoning: [`DESIGN-V2.md`](DESIGN-V2.md).

## Status

All six planned v2 phases (Rust core, persistent service, lead memory, settlement, narrative, data layer) are built and verified against concrete proof conditions — see `DESIGN-V2.md` for what each one required and `LOG.md` for the full account, including what didn't work on the first try. One thing is deliberately still open: whether the narrative reads well and the settlement is worth actually stewarding is a human judgment call the build itself can't confirm, same as v1 gave its own live-feel work.

## Tech

**v1**: Python (standard library only for the simulation core), pygame for the live view, Ollama for local LLM inference.
**v2**: Rust (`tokio`, `axum`, `tokio-postgres`) for the core and service, the same Python + Ollama for LLM orchestration, PostgreSQL for the data layer. No API keys required anywhere, in either version.

## License

[MIT](LICENSE)
