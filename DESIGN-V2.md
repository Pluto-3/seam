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
- **Phase 2 — Leads: memory + visible identity.** Add the two-layer memory
  (counters + periodic self-summary) and surface name/goal/personality in the
  viewer for both leads and crowd (crowd's batched spawn-time identity).
  **Proof:** run long enough for a lead to hit a real bad-trade streak or a
  real hunger scare, and show its decision distribution measurably shifts
  after the self-summary fires, compared to a run where it doesn't — the same
  before/after comparison method already used to validate the crowd
  mechanic in v1.
- **Phase 3 — Hatch: steward.** Bind the player to a specific settlement,
  build the settlement health metric, wire up direct possession (ported from
  v1) and standing orders for the player. **Proof:** one playtest where a
  deliberately neglected settlement visibly declines, and one where active
  stewardship visibly recovers or grows it — the stakes have to be real and
  observable, not just present in code.
- **Phase 4 — Narrative generation.** Periodic scene-writing LLM calls
  reading across leads + the player's settlement, surfaced as a live feed in
  the viewer. **Proof:** a multi-hour run produces a feed a person would
  actually choose to read, not a formatted log line — this is a human
  judgment call the build itself can't confirm, same caveat v1 gave Phase 1's
  "does it read well."
- **Phase 5 — Data layer + exporters.** Move logging to PostgreSQL, update
  the three exporters to read the richer lead/crowd data (memory summaries,
  settlement health, narrative scenes). Waypoint/other downstream integration
  stays optional here, per the reuse principle — nothing about this phase
  requires it. **Proof:** all three exporters run against a real v2 run and
  produce output at least as useful as their v1 equivalents, now with the
  new data available to query.

## Open questions

None blocking Phase 0. Still genuinely open, deferred on purpose:

- **How far does "real ass world" scale go, and when?** Not a v2 target —
  the Rust/service architecture is meant to not block it later, that's all.
- **Monetization.** Explicitly deferred per `V2.md` — plumbing stays live,
  nothing here is a v2 build target on its own.
- **Patron/rival-to-one-lead player variant.** Considered and set aside for
  now — it depends on lead memory existing first (Phase 2), so it's a
  candidate addition after Phase 2/3, not a Phase 0 decision.
