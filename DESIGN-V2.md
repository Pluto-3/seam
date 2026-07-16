# Seam v2 — design + build plan

This is the v2 counterpart to `DESIGN.md`. It does not repeat what v1 already
settled and v2 keeps unchanged — world-as-graph, the seven actions, the
tick-log-is-the-only-output principle, the three-exporter concept. Read
`DESIGN.md` and `LOG.md` first; this document only covers what's new or
changed for v2. `V2.md` is the carry-forward sketch that led here — this
document is what it asked for: the sketch turned into staged, verifiable
phases.

## What's carried over unchanged from v1

- World as a graph (nodes = places, edges = routed travel), rendered
  continuously rather than tile-by-tile.
- The seven actions (move, gather, consume, trade, rest, craft, signal) and
  the raw/refined crafting split.
- Tick logging as the single source of truth; exporters are read-only filters
  over it, never touching the sim.
- The congestion fix and emergency-food-routing fix (ported logic, not
  redesigned).
- The argmax-fallback pattern: any lead-reasoning failure degrades to
  crowd-like scoring instead of breaking.

## What's new or changed in v2

### Tech stack
- **Simulation core: Rust.** A port of the proven Python logic
  (world/agents/decide/actions/tick), not a redesign.
- **LLM orchestration (lead reasoning, memory summarization, narrative
  generation): Python sidecar**, talking to the Rust core over an API.
- **Viewer: React web app** over WebSocket (live state) + REST (control:
  possess, standing orders, settings, reports) — replaces pygame.
- **Data layer: PostgreSQL** — replaces flat CSV/JSONL.
- **Architecture split:** a persistent simulation service (ticks
  continuously, independent of viewers) and a viewer that connects/
  disconnects without stopping the world. This is what makes hybrid
  persistence (leave it running, or don't start it) actually work.

### Crowd tier
No reasoning change — stays mechanical/cheap/numerous. New: a name + one-line
identity generated once at spawn, one batched LLM call for the whole crowd
(not per-tick), so zooming in on any crowd agent shows a person, not `a12`.

### Lead tier — memory (resolved this session)
Two layers, not one:
1. **Structured counters, updated every tick, no LLM cost.** Recent trade
   win/loss ratio, hunger-scares witnessed, stock trend at the settlement
   they care about. Cheap, bounded, always current.
2. **Periodic self-summary, one LLM call every ~100-300 ticks.** The lead
   reads its own counters + recent raw events and writes a short first-person
   note ("trading's gone badly, I'm getting cautious"). This note is:
   - fed back into future decision prompts as memory context, and
   - allowed to shift the lead's goal-weighting (a "cautious" self-summary
     measurably lowers how the lead scores risky trades) — memory that
     changes the *goal*, not just flavor text, which is what the open
     question specifically asked for.
   - reused, unmodified, as first-draft raw material for narrative
     generation (see below) — one LLM call, two consumers.

### Narrative generation (resolved this session)
Periodic (same rough cadence as the self-summary, or triggered by a notable-
event cluster — a death, a settlement crisis), one LLM call reads what
happened across all leads plus the player's settlement and writes a short
scene, not a per-event log line. Surfaces in the viewer as a scrollable live
feed, not a report you have to go generate separately. Reuses the
async/never-blocks pattern already proven necessary in v1.

### Player purpose (resolved this session)
**The hatch is steward of a settlement.** The player is bound to a specific
settlement whose survival and prosperity are the actual stake — neglect it
and it can genuinely collapse, tend it and it grows. Two ways to act on that,
both already half-built in v1:
- **Direct possession** — walk, gather, trade, defend, in person, as the
  hatch character (already exists).
- **Standing orders** — the same order-issuing mechanic leads already use on
  crowd agents ("everyone gather wood"), extended to the player. Almost free
  to build since the mechanic is proven; this is what makes the CCTV framing
  (watch, then climb in and shape things) real instead of "walk around and
  do chores yourself."

New concept this requires, not present in v1: which crowd agents/resources
count as "the player's settlement," and a health metric (something like the
crowd survival/stock signals v1 already logs, scoped to one settlement)
that can visibly rise or fall.

## Build plan

Phased the same way v1 was — each phase only starts once the one before it
proves worth continuing, and each has a concrete pass/fail check, not just
"done when built."

- **Phase 0 — Rust core parity. DONE, 2026-07-15.** Ported world/agents/
  decide/actions/tick (including the congestion fix and emergency-food-
  routing fix) to Rust (`core-rs/`), headless, no viewer, no leads, no
  player. Compiled clean first try; selftest passed. Re-ran the same 20-seed
  (1-20) paired trade-on/trade-off comparison from `LOG.md` at 8000 ticks:
  Python reproduced its own recorded numbers exactly (confirming the
  baseline hadn't drifted), Rust matched at comparable magnitude -
  specialization index 0.491 vs Python's 0.490, trade-on beating trade-off
  in 17/20 (Rust) vs 16/20 (Python) seeds. One Rust seed showed a population
  decline to 24/40; re-running Python on 53 seeds outside the original
  tested range surfaced the same phenomenon at a similar rate (down to
  22/40 in one case), confirming it's a genuine pre-existing property of
  the mechanic - not a Rust translation bug. Full account, including the
  RNG-parity decision (statistical, not bit-exact) and a real disk-space
  snag during the batch runs, in `LOG.md`.
- **Phase 1 — Service/viewer split. DONE, 2026-07-15.** Wrapped the Rust
  core as a persistent service (`core-rs/src/serve_main.rs`, a second binary
  alongside the headless `run`): a background async task ticks the world on
  its own clock, a `/state` REST endpoint and a `/ws` live-push endpoint
  expose it, and a static HTML/JS page at `/` connects/disconnects freely
  without affecting the sim underneath. **Deliberately built the viewer as a
  single dependency-free HTML file, not React** - the disk was already tight
  from Phase 0 (15GB free on a 468GB disk) and a full npm/Vite/React
  toolchain risked adding a large, uncertain footprint for something this
  phase's proof doesn't actually require; a real React rewrite is deferred
  to whenever richer UI needs justify it, not treated as owed by default.
  Also deferred: the Python sidecar - Phase 1's proof doesn't need it, and
  a pass-through with no logic yet was scaffolding without a job; it lands
  in Phase 2 when leads actually need LLM orchestration. **Proof:** ran the
  service, connected over WebSocket, disconnected fully, waited 5 real
  seconds with zero viewers attached, reconnected, and confirmed the tick
  counter had advanced by 96 ticks (~600→~698) the entire time no one was
  watching - the literal "world keeps existing whether or not anyone's
  watching" claim, verified end-to-end, not assumed.
- **Phase 2 — Leads: memory + visible identity. DONE, 2026-07-15.** Added
  the two-layer memory: a mechanical `caution_bias` recomputed every tick
  straight from free counters (trade success ratio, hunger scares witnessed)
  - no LLM involved, so it shifts scoring even on ticks the model hasn't
  answered on - plus an LLM-authored `memory_summary` fed into future prompts
  and shown in the viewer alongside name/goal/personality for both leads and
  crowd (crowd's batched spawn-time identity, via the new Python sidecar at
  `sidecar/sidecar.py`). Splitting the mechanical number from the narrative
  text (rather than asking one LLM call for both) was a refinement made
  during the build, not planned upfront - see `LOG.md` for why. **Proof:**
  live-verified against real Ollama first (real, distinct self-summaries,
  a manual override posted and confirmed applied one tick later), then
  proven properly with a controlled experiment - a `memory_enabled` toggle
  isolates the mechanical layer from live-model timing, run across 15 seeds
  x 2 conditions, 3 leads each. Found trade activity increases after a
  hunger scare in both conditions, but measurably less with memory on
  (+19.3 percentage points vs +22.2) - a real, modest, directionally
  consistent effect attributable specifically to the memory mechanism, not
  the larger effect originally expected. Reported at that size, not rounded
  up - see `LOG.md`.
- **Phase 3 — Hatch: steward. DONE, 2026-07-16.** Bound the player to a
  settlement (one designated node + a fixed roster of 8 relocated crowd
  agents, so an unlucky seed can never hand the player an empty one), built
  the health metric as raw numbers (population, avg hunger/energy, food
  held - no composite score, per the discussion beforehand), and added the
  hatch - a new agent mechanically identical to a lead, except nothing
  drives it automatically; it just waits for `POST /player/action`.
  Standing orders needed no new code at all - the hatch issuing `SIGNAL
  order:food` is the exact mechanic from Phase 0. **Proof:** took two real
  attempts to get right, not a straight line - the first seed turned out to
  be an "easy" world where the settlement thrived regardless of tending,
  so switched to seed 19 (Phase 0's known hard case). Even then the first
  comparison looked unconvincing until the full trajectory (not just
  endpoints) was checked, which exposed two real bugs in the *test*
  reasoning: the standing-order signal expires in 30 ticks and wasn't being
  refreshed often enough, and it was being tried last instead of first when
  it's the systemic lever. Fixed both and re-ran: neglected hits its
  population floor by tick ~1028 and stays there; tended holds full
  population until tick ~803 and doesn't reach that same floor until tick
  ~3749 - over 3.5x longer. Real and substantial, more precisely described
  as delaying/softening decline than "growth" - see `LOG.md` for the full
  account, including why the first two attempts didn't show it.
- **Phase 4 — Narrative generation. BUILT, 2026-07-16 - awaiting human read.**
  A capped rolling feed (`GET`/`POST /narrative`) written by a third periodic
  sidecar task reading across leads + the settlement, folded into the
  existing snapshot push so the viewer needed only a new panel, not a new
  polling mechanism. **A real quality problem was caught before shipping,
  not after**: the first prompt asked the model to "narrate a scene" and it
  invented people, objects, and a whole storyline with none of it grounded
  in what the sim actually tracks - and continuity (feeding the previous
  scene back in) compounded the fabrication across cycles rather than
  correcting it. Fixed by reframing the ask as "write a status report using
  ONLY the facts given" rather than open-ended scene-writing; re-verified
  clean afterward. **Proof is still the human judgment call it always was**
  - the mechanism works and no longer fabricates, but whether the writing
  is actually good enough to want to read needs a person looking at the
  live feed, same as v1's own "does it read well" for Phase 1. See `LOG.md`
  for the full account of what the hallucination looked like and why the
  fix worked.
- **Phase 5 — Data layer + exporters. DONE, 2026-07-16 — last phase.** Added
  a lean four-table Postgres schema (`core-rs/schema.sql`): events (same
  lead/death entries as JSONL, plus `specialty` - closing a real
  documented v1 gap), lead memory, narrative scenes, settlement health, all
  additive alongside the existing JSONL/CSV logging in `serve`
  (`--postgres-url`/`--run-id`). All three exporters gained a Postgres mode
  alongside their existing `--log-path` mode, verified to match v1 output
  exactly in JSONL mode and to produce real, working output against a live
  v2 run. `export_narrative.py` got a genuine upgrade: Phase 4's real
  authored scenes now merge into the timeline at their actual tick,
  alongside the templated event lines. `export_strategy.py` computes
  specialization index directly from logged specialty now, instead of the
  old paired-CSV workaround. **A real toolchain problem surfaced and got
  fixed properly**: a modern Postgres crate needed Cargo's edition2024,
  unsupported by the apt-installed Rust 1.75 from Phase 0 - rechecked
  whether the original constraint (slow network, why rustup was skipped)
  still held, found it didn't, and `rustup default stable` fixed both the
  edition2024 problem and the unrelated broken `~/.cargo/bin/cargo` shim in
  one move. See `LOG.md` for the full account. Waypoint/other downstream
  integration was left optional throughout, per the reuse principle -
  nothing about this phase required it.

This is the last of the six planned phases. Full account of the whole
build, phase by phase, including what was learned and what wasn't a
straight line, in `LOG.md`.

## Open questions

None blocking Phase 0. Still genuinely open, deferred on purpose:

- **How far does "real ass world" scale go, and when?** Not a v2 target —
  the Rust/service architecture is meant to not block it later, that's all.
- **Monetization.** Explicitly deferred per `V2.md` — plumbing stays live,
  nothing here is a v2 build target on its own.
- **Patron/rival-to-one-lead player variant.** Considered and set aside for
  now — it depends on lead memory existing first (Phase 2), so it's a
  candidate addition after Phase 2/3, not a Phase 0 decision.
