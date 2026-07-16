# Seam v3 — design + build plan (Watchable World)

This is the v3 counterpart to `DESIGN.md` and `DESIGN-V2.md`. It does not
repeat what v1/v2 already settled and v3 keeps unchanged — world-as-graph,
the seven actions, node-scoped signals, tick logging as the only source of
truth, the two-layer lead memory, the hatch/standing-order mechanic, the
persistent service + viewer split. Read `DESIGN.md`, `DESIGN-V2.md`, and
`LOG.md` first; this document only covers what's new or changed for v3.
`V3.md` is the carry-forward sketch that led here — this is what it asked
for: the sketch turned into staged, verifiable phases.

## What's carried over unchanged from v2

- World as a graph, one shared world — v3 does not introduce multiple
  worlds (see below for why).
- The seven actions, unchanged. No new action type is needed for societies
  or rivalry.
- Node-scoped signals (`node.signals` in `decide.rs`) — standing orders and
  scarce/rich broadcasts already only affect agents at or near that specific
  node, not the whole world. Confirmed by reading the mechanic directly, not
  assumed — this is the reason a shared world produces real locality for
  free (see below).
- Trade as a plain two-agent mechanic with no concept of "which settlement" —
  already works between any two agents regardless of origin.
- The congestion mechanic (the proven collapse driver — 9.3 vs 1.57 agents
  piling per gather attempt at 15 vs 25 nodes, same seed) — already creates
  real contention pressure wherever two groups compete for the same scarce
  node.
- Lead two-layer memory, hatch/standing-orders, narrative generation,
  Postgres data layer, all exporters — unchanged, extended to read across
  multiple societies rather than replaced.

## What's new or changed in v3

### Core generalization: one settlement → N societies (resolved this session)

Today's code already does this shape once: `spawn_leads` (`agents.rs`)
creates a fixed 3 leads at random locations, and `serve_main.rs` designates
exactly one settlement — `world.node_order[0]` plus a fixed roster of 8
crowd agents relocated there at spawn. v3 generalizes both into a loop over
N societies (a config parameter, default small — start at 3, not dozens):
each society gets a home node (spread across `world.node_order`, not
adjacent — exact spacing method is an implementation detail, not a design
question), a fixed roster of crowd agents relocated there, and one lead
whose *initial* location is that home node instead of random (leads still
move freely after spawn, same as today — only the starting condition
changes). Every society also gets its own hatch-eligible agent slot (see
Player possession, below).

**Society count is fixed per run, not dynamically formed or dissolved in
v3's core build.** Same phased discipline as everywhere else in this
project — prove the small, fixed case produces real watchable behavior
before taking on the much larger problem of societies forming, merging, or
ending outright. Dynamic society lifecycle is a real open question, deferred
on purpose (see Open Questions).

### Shared world, not separate worlds (resolved this session)

**Decision: one graph, N societies placed at different nodes on it — not N
independent simulations linked by trade/narrative.** This was `V3.md`'s
central open fork, and it cascades into most of the others, so it's worth
stating the reasoning plainly:

- Signals are already node-scoped, confirmed in `decide.rs` — a standing
  order or scarce/rich broadcast only affects agents at that node. Real
  locality between rival societies falls out of physical distance on the
  shared graph, for free, with zero new mechanic.
- Trade has no concept of "home settlement" today — two agents from
  different societies meeting at a shared or contested node can already
  trade, unmodified.
- The congestion mechanic already produces real contention pressure the
  moment two groups compete for the same scarce node — this is the actual
  mechanism a "rivalry" needs, and it already exists.
- A separate-worlds design would require inventing a cross-world
  trade/messaging protocol from nothing — real, non-trivial new work with no
  existing mechanic to lean on, against this project's stated reuse posture
  (lean on what's proven, don't build a parallel system when one already
  does the job).

Shared world wins cleanly on reuse, and it's what makes rivalry-by-physical-
proximity possible instead of something that has to be invented separately.

### Player possession (resolved this session)

One hatch mechanic, extended rather than multiplied: every society has its
own hatch-eligible agent, but the player controls exactly one at a time via
a possession pointer that can be reassigned (a new endpoint, working name
`POST /player/possess/:society_id`) — everything under actual control still
goes through the existing unmodified `POST /player/action`. An unpossessed
hatch just runs the existing argmax/autopilot fallback — this needs no new
code path, it's the same "absence of an active decision defaults to
autopilot" guarantee already proven for leads in v2 Phase 2, applying
unchanged to a hatch nobody's currently steering. This matches the
Rick-climbing-into-whichever-battery-he-wants framing better than locking
the player permanently to one society.

### Viewer: society navigation (resolved this session)

No rebuild — the existing single-page viewer gains a society switcher
(tabs) plus a comparative overview panel showing the same raw per-society
numbers already shown for one settlement today (population, avg
hunger/energy, food held), side by side across all N. Selecting a society
shows the existing detail panels (settlement/hatch/leads) scoped to it.
Reuses the existing snapshot/WebSocket push mechanism unchanged — no new
polling infrastructure.

### Rivalry: implicit first, explicit deferred (resolved this session)

v3's core build adds no formal alliance/hostility/claim mechanic. Rivalry
starts purely implicit — shared-node contention plus cross-society trade,
both already-proven mechanics that the shared-world decision extends for
free. Same discipline as v1 Phase 0 (prove a mechanic produces real,
watchable behavior before investing further): Phase 3 below is specifically
the test of whether implicit contention alone is enough to feel like real
stakes. A formal rivalry mechanic (claims, alliances, explicit hostility)
only becomes a real candidate if that test says the implicit version is too
quiet — not built speculatively ahead of that answer.

### Highlight extraction (resolved this session — direction only, thresholds deferred)

Defined as: an already-logged rare event (death, a standing order actually
applied, an LLM-authored narrative scene) that also carries a cross-society
signal — concretely, a trade between agents whose home-society rosters
differ, a death at or near a different society's home node, or two
societies' leads both signaling/contesting the same node in a short window.
This reuses the existing event stream exactly as-is — grepping it for the
condition above, not adding new logging — the same read-only-filter posture
every exporter already follows. Exact thresholds (what counts as "near,"
what window counts as "concurrent") are deliberately left to implementation
and tuned against real N-society data, the same way Phase 4's narrative
prompt in v2 couldn't be judged right until real output existed to read.

## Build plan

Phased the same way v1 and v2 were — each phase needs a concrete proof
condition, not "feels done," and later phases don't start until earlier
ones are proven worth continuing.

- **Phase 0 — Multi-society core. DONE, 2026-07-16.** Generalized the
  settlement-roster loop into a `Society` struct (`serve_main.rs`) built in
  a loop over `--societies` (default 3, matching `LEAD_GOALS.len()`) instead
  of a single hardcoded settlement; added `spawn_leads_at` (`agents.rs`) so
  each lead's *initial* location is its society's home node instead of
  random, and a new `pick_spread_nodes` (`world.rs`) — greedy farthest-point
  BFS over real hop-distance, not just `node_order` slicing, so societies
  don't spawn clustered together (covered by a unit test against the actual
  default seed/node-count, not a hand-picked easy case). `Snapshot.settlement`
  /`.hatch` became `Snapshot.societies: Vec<...>`, `GET /settlement` became
  `GET /societies`. Zero changes to `decide.rs`/`tick.rs`, confirmed by
  reading the scoring code directly before starting — signals are already
  node-scoped, trade has no concept of "home settlement." **Known, accepted
  temporary breakage**: the existing `viewer/index.html` reads singular
  `settlement`/`hatch` fields that no longer exist — its settlement/hatch
  panels won't work again until Phase 2. `/player/action` and
  `/player/candidates` still hardcode society 0's hatch — Phase 1's job, not
  built yet. **Proof:** ran `serve` for a real stretch (1,783 ticks, 40
  agents, 3 societies at `n0`/`n5`/`n7`) with full logging and checked the
  actual event log rather than asserting the mechanic works — found 22,894
  cross-society TRADE attempts (16,934 successful) and 21,973 real instances
  of two different societies' agents occupying the same node in the same
  tick. The shared-world bet paid off exactly as reasoned: real rivalry-by-
  contention emerged from mechanics that already existed, with no new code
  in the tick engine at all.
- **Phase 1 — Player possession across societies. DONE, 2026-07-16.** Added
  `SimState.possessed_society` (defaults to society 0, preserving Phase 0's
  exact prior behavior) and `POST /player/possess/:society_id`, which 404s
  on an unknown id and clears any stale `pending_intents` entry for the
  *previous* hatch so a queued-but-not-yet-applied action can't leak onto
  the old hatch after a switch. `get_player_candidates`/`post_player_action`
  now resolve the current hatch via a small `possessed_hatch_id` helper
  instead of a hardcoded constant — `DEFAULT_HATCH_ID` is gone. `Snapshot`
  gained `possessed_society` (additive, for Phase 2's viewer to show
  "currently yours" later). No changes to `decide.rs`/`tick.rs`/
  `agents.rs`/`world.rs` — confirmed this phase was purely about *which*
  hatch existing mechanisms point at. **Proof:** verified on a live `serve`
  instance (slowed to `--tick-ms 500` specifically to make timing
  unambiguous) — switched possession from society 0 to society 1, submitted
  one `REST` action, and confirmed via the event log it landed on `hatch1`
  on the exact next tick (tick 31, one after the tick read immediately
  before posting); `hatch0` kept autopiloting continuously across the same
  window (`SIGNAL`/`GATHER`/`REST`/`MOVE` on its own, zero operator input)
  with no lag from losing possession. 404 on an unknown society id
  confirmed not to mutate `possessed_society`. Existing headless `run`
  binary's selftest still passes.
- **Phase 2 — Viewer: society switcher + overview.** Add tab navigation and
  the comparative raw-numbers panel. **Proof:** switch between all N
  societies live, with no disconnect or restart — the same non-blocking
  precedent as v2 Phase 1's "world ticks with zero viewers," extended to
  "switching focus doesn't disturb what's not currently being looked at."
- **Phase 3 — Implicit rivalry stress test.** Run N societies for a real
  stretch (same discipline as the three parallel hard-seed experiments
  already run post-v2), specifically checking whether shared-node
  contention and cross-society trade produce a noticeably more watchable
  dynamic than N independent single-settlement worlds would. This phase's
  result decides whether an explicit rivalry mechanic is worth building at
  all — an honest human judgment call, flagged as such up front, the same
  way v2 Phase 4's narrative quality was.
- **Phase 4 — Highlight extraction.** Build the cross-society-signal filter
  over the existing event log; surface it as a feed or export, following
  the exact non-blocking, read-only-filter posture the three existing
  exporters already use. **Proof:** run for a real stretch, confirm the
  highlight feed surfaces events a human agrees are actually notable, not
  merely frequent — explicitly a human judgment call, same posture as v2
  Phase 4's narrative check.

## Open questions

None blocking Phase 0. Still genuinely open, deferred on purpose:

- **Dynamic society formation/failure.** A society hitting population zero
  just sits at its floor today, same as the existing single-settlement
  collapse behavior. Whether that should mean something more (real
  dissolution, absorption into a neighboring society) is deferred until the
  fixed-N core is actually running and there's something real to observe.
- **Explicit rivalry mechanics** (formal alliances, claims, war). Only a
  real candidate if Phase 3 finds implicit contention too quiet to be
  interesting.
- **How many societies, eventually, and does the graph need to grow to fit
  them.** Same "how far does the real-ass-world scale ambition go" posture
  v2 left deferred — not a v3 build target, just something the design
  shouldn't block later.
- **Monetization.** Still explicitly deferred, unchanged from v2 — plumbing
  stays live, nothing here is a build target on its own.
