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
  built yet. **Proof:** ran `serve` for a real stretch with full logging and
  checked the actual event log rather than asserting the mechanic works —
  found real cross-society TRADE attempts and real instances of two
  different societies' agents occupying the same node in the same tick. The
  shared-world bet paid off exactly as reasoned: real rivalry-by-contention
  emerged from mechanics that already existed, with no new code in the tick
  engine at all. **Correction, made during Phase 3 (2026-07-16):** the
  original figures quoted here (22,894/36,201 cross-society trades, ~63%)
  were computed with ad hoc interactive Python against a log file that was
  still growing in the background mid-analysis — the trade-count denominator
  and the cross-society numerator ended up read from different moments of
  the same live-appending file, not one consistent snapshot, and the
  "1,783 ticks" scope quoted alongside them belonged to an even earlier read.
  Rebuilding the same check as a real, rerunnable script
  (`analyze_cross_society.py`) against a properly frozen slice of that same
  run found the actual cross-society trade rate is **~28-32%**, not 63% —
  still a real, substantial finding (roughly a third of all trading was
  already happening across society lines with zero purpose-built rivalry
  mechanic), just meaningfully smaller than first reported. Left uncorrected
  here until Phase 3 caught it precisely because there was no script to
  rerun — exactly the gap Phase 3 was scoped to close. See Phase 3's entry
  below for the corrected, reproducible numbers.
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
- **Phase 2 — Viewer: society switcher + overview. DONE, 2026-07-16.** The
  cards double as the switcher, per a direct decision (not assumed): one row
  of `.society-card` buttons (`renderSocieties`, `viewer/index.html`) shows
  every society's raw numbers side by side, and clicking one both scopes
  the settlement/hatch/leads panels below to it and calls the new `POST
  /player/possess/:id` — one interaction, not a read-only tab strip plus a
  separate possess button. `snap.possessed_society` (Phase 1) is the single
  source of truth for both which card is highlighted and which society's
  data renders — no client-side "selected" state to drift out of sync.
  `refreshHatchActions`/`submitHatchAction` needed zero changes; they
  already transparently followed server-side possession since Phase 1.
  **One small backend addition found while planning this**: `Society`
  (Phase 0) stored `hatch_id` but never `lead_id`, even though
  `spawn_leads_at` already pairs lead *i* with society *i* by construction —
  that pairing existed only as an implicit ordering convention until now,
  needed to scope the leads panel correctly instead of guessing from index.
  Also reset `settlementHistory` whenever the focused society's id changes,
  so switching doesn't splice two societies' numbers into one misleading
  sparkline line. **Proof:** verified against a live `serve` instance with
  real headless-Chrome DOM dumps (not just reading the code) — confirmed 3
  distinct cards with correct per-society numbers, the default-possessed
  card highlighted, then switched possession via the same API call the
  button's `onclick` makes and re-dumped: highlight moved, `the settlement
  (society1)`/`the hatch (you, society1)` labels updated, leads panel
  correctly showed only `lead1` (not all three), and `/player/candidates`
  returned real candidates for the new hatch. Zero JS console errors across
  both loads. Existing headless `run` selftest still passes.
- **Phase 3 — Implicit rivalry stress test. DONE, 2026-07-16.** Not a code
  build (aside from one new script) — an experiment deciding whether
  implicit contention is enough, or whether an explicit rivalry mechanic
  needs building on top of it. **New reusable tool**: `analyze_cross_
  society.py` (repo root), since no existing script computed a
  cross-society metric — the Phase 0 numbers had been an uncommitted,
  ad hoc pass. Society membership is reconstructed by identity, not
  cluster size: a hatch/lead's location is never random (deliberately
  spawned at its society's home node), so real home nodes are wherever a
  `hatch*`/`lead*` id's earliest location is — a size-based cutoff was
  tried first and failed a real test (an isolated-baseline run's larger
  free-roaming crowd pool produced random spawn-collisions big enough to
  misread as a phantom second society), caught by testing against real
  data before trusting it, not assumed safe.
  **A real correction fell out of building this properly**: the original
  Phase 0 headline (22,894/36,201 ≈ 63% cross-society trades) turned out to
  be computed against a log that was still growing mid-analysis — numerator
  and denominator weren't actually one consistent snapshot. Corrected in
  Phase 0's own entry above; the real, reproducible rate is ~28-32%, still
  substantial.
  **Six varied runs** (3 shared-world at `--societies 3`, 3 matched
  isolated-baseline at `--societies 1`, each pair at the same seed/node
  count — seed 42/15 nodes, seed 19/15 nodes [harsher economy, 88.3% gather
  fail], seed 31/25 nodes), ~5,000-5,200 ticks each, logs frozen (processes
  stopped) before analysis specifically to avoid repeating the mid-growth
  measurement mistake. **Quantitative result, held up across all three
  varied configs, not just one**: 29.2-31.9% of all trades and 45.8-59.6%
  of node-occupancy groups were cross-society in every shared-world run;
  structurally exactly 0% in every isolated-baseline run, as expected by
  construction. **Qualitative result, read from real log entries, not
  inferred from percentages**: cross-society trades appear from as early
  as tick 4 and recur steadily throughout a run, not a rare fluke — and in
  the harshest-economy seed, all three of that run's deaths happened at the
  same single contested node (`n13`), with all three societies' leads and
  two of three hatches simultaneously present at that tick. That's a real,
  narratively rich moment (a genuine three-way convergence under scarcity
  pressure) that emerged with zero purpose-built rivalry code.
  **Honest caveat, stated rather than glossed over**: the isolated
  baseline's structural 0% is airtight (no second society exists to trade
  or contend with, full stop), but it always gets only `lead0`'s
  "wealthiest trader" personality, never a fair sample of all three — not
  a confound for the cross-society-rate metric itself (which is 0 by
  construction regardless of which lead is present), but worth remembering
  if this baseline is ever reused to compare behavioral variety instead.
  **Verdict**: implicit contention is enough for now. It's frequent,
  consistent across varied seeds/topologies, and produces at least one
  genuinely dramatic real moment without any explicit rivalry mechanic
  built. Recommendation: proceed to Phase 4 (surface what's already
  happening) rather than build formal alliances/hostility on spec — revisit
  explicit rivalry only if Phase 4's highlight extraction finds the
  implicit version starts feeling repetitive over much longer stretches, a
  genuinely open follow-up question this one experiment doesn't resolve.
- **Phase 4 — Highlight extraction. DONE, 2026-07-16.** Extends the
  existing `sim.notable_events` live feed rather than building a new
  offline export — a `society_of(sim, agent_id)` helper (no prior lookup
  resolved an arbitrary agent to its society) tags two new highlight kinds:
  `cross_trade` (a lead/hatch's own successful trade with an agent from a
  different society — reuses the exact lead/hatch tier gate already
  proven for standing orders, the actual curation mechanism that keeps
  Phase 3's ~30% baseline crowd-crowd cross-trade rate from flooding a
  feed meant to be rare) and `foreign_death` (a death at a different
  society's home node — additive alongside the existing plain `death`
  entry, not replacing it, so population-tracking isn't affected by
  whether a given death also qualifies as a highlight).
  **Two real problems found during live verification, both fixed, not
  glossed over.** First: cross_trade/foreign_death initially shared the
  existing `events` feed's 30-slot cap with routine `order` entries —
  under this seed's scarcity, orders fire so often that **268 real,
  correctly-detected cross-society trades occurred and zero survived** in
  the live feed by the time it was checked. Fixed by giving highlights
  their own separate, smaller feed (`highlights`, cap 20) so routine
  activity can't crowd them out — a genuine, tested need, not
  speculative. Second: even in its own feed, one recurring relationship
  (a hatch parked near a border, repeatedly trading the same one or two
  crowd partners) monopolized all 20 slots — correct detections, but not
  a *highlight* repeated fifteen times. Fixed with a per-pair cooldown
  (`CROSS_TRADE_HIGHLIGHT_COOLDOWN`, 300 ticks), the same cooldown concept
  `decide.rs`'s `SIGNAL_COOLDOWN`/`can_signal` already uses for signal
  spam, applied to a trading pair instead. Also fixed a latent viewer bug
  found while touching this code: `renderEvents`'s second branch was a
  bare `else`, not `else if (kind === "order")` — any new kind added
  without an explicit branch would have silently rendered as a broken
  order line.
  **Proof, after both fixes**: a fresh live run (seed 19, the harshest
  economy from Phase 3) produced 20 highlights with **zero repeated
  pairs**, involving all four leads/hatches, not one — confirmed via
  headless-Chrome DOM dump that the new `highlights` panel renders
  correctly and the existing `events` panel is unaffected (regression
  check on the bug fix). Human judgment call, stated honestly: lead-vs-lead
  and lead-vs-hatch cross-society trades read as genuinely interesting
  (named characters with real goals/personalities crossing society
  lines); a lead/hatch trading with an anonymous crowd id is real but
  less narratively rich until that crowd member has its own identity.
  `foreign_death` never fired in this run (0 of several deaths) — an
  honest null result, consistent with Phase 3's own raw-log check also
  finding 0 qualifying deaths; the mechanism is real but this event type
  is evidently rare at this scale, not proven wrong, just unobserved yet.

## Phase 5 — Relationships / memory-of-others (core built + verified 2026-07-20; see LOG.md)

**Decision, not yet built.** External research (`LOG.md`, 2026-07-20 entry) surfaced the actual gap behind the Watchable World ambition: Project Sid's most-cited emergent moment (two agents forming a relationship, turning on their own town's leadership) came from agents holding real memory of *each other*, not richer stats about themselves. Seam doesn't have that today — leads reason from their own two-layer memory in isolation, crowd agents carry no memory of other agents at all, and standing orders are one-directional (leads/hatch issue them, nobody signals back). This phase closes that gap for real, not as a bolt-on:

- **Per-agent relationship state** — at minimum leads and hatches (crowd stays cheap/mechanical per the project's standing reuse posture, same tier discipline as every phase before this), tracking real history with specific other agents: trade partners and outcomes, rivalry/contention at shared nodes, anything Phase 3's cross-society highlight extraction already detects as noteworthy.
- **A feedback channel, not just top-down orders** — the hierarchical-team literature (`LOG.md`) found lead-style agents issue the large majority of a team's one-way communication; this phase adds the other direction, crowd/lower agents signaling something back upward that a lead's own decisions or memory summary can actually use.
- **Narrative and highlights read relationship state, not just raw events** — the eventual payoff: a scene or highlight can reference an actual standing relationship ("lead0's third dispute with lead2 over n13") instead of only a single tick's isolated event.

Concordia's Entity-Component pattern (`LOG.md`) is worth a skim before committing to a concrete data shape for relationship state — not to adopt Concordia wholesale, but cheap insurance against re-deriving a structure it already iterated on.

**Built and verified 2026-07-20 (LOG.md has the full account)**: `relationships: HashMap<String, RelationshipRecord>` on every `AgentState`, populated at trade resolution, node-contention, and standing-order attribution (via `Signal.posted_by`, previously unused); a mechanical `top_relationships(n)` feeds both the viewer (`public_view()`) and `sidecar.py`'s memory prompt. Verified with two Rust unit tests (positive + negative control) and a live Ollama run where a lead's `memory_summary` correctly referenced its real top relationship by id. Deliberately not yet built: a crowd-wide aggregate ("how many distinct agents follow lead0's orders") — the per-agent data this needs now exists, computing the aggregate itself is a straightforward follow-up, not done this session.

## Research thread — Asymmetric-power campaign (run + resolved 2026-07-20; see LOG.md)

**Result**: mixed, honest, not the clean SOVSIM story. Trade activity declines close to monotonically as `order_strength` increases (mean ~19.1k trades at symmetric down to ~15.0k at strong asymmetry, ~21.5% drop across 15 seeds x 5 levels) - the SOVSIM-consistent finding. Population/survival mostly does not degrade with asymmetry (14/15 seeds show zero deaths at any level) - one seed has a sharp collapse threshold between levels 2.0 and 2.5 specifically, a second shows a milder non-monotonic effect - population collapse under asymmetry is real but rare and seed-specific here, not a general effect. Full numbers and the two exception seeds are in `LOG.md`'s 2026-07-20 entry; raw per-run results in `core-rs/logs/asymmetric_power_campaign_2026-07-20.csv`.



**Decision, not yet run.** A 2026 paper (SOVSIM, `LOG.md`) found that introducing one asymmetric-power agent into an otherwise-symmetric population caused up to 87% degradation in cooperation/survival across eleven models. Seam's lead/hatch-over-crowd design is structurally the same shape. This is locked as a dedicated, rigorous experiment — not a quick check of existing logs, since the raw per-decision data from July's long runs was deleted in the disk near-miss:

- Multiple asymmetry *levels* (not just a memory-on/off-style binary toggle) — needs a real tunable "how much power does a lead/hatch actually hold over nearby crowd decisions" parameter, which doesn't exist yet.
- Multiple seeds per level, same statistical rigor as the original 20-seed trade-on/off proof and the Phase 2 memory on/off experiment.
- The actual question: does seam's own stewardship result (tended settlement surviving 3.5x longer) hold *because* the design avoids the cooperation-collapse this paper describes, or is it quietly paying a cost elsewhere that hasn't been measured?

This can run independently of Phase 5 and doesn't block it, but both are informed by the same research pass and are being planned together.

## Open questions

None blocking Phase 0. Still genuinely open, deferred on purpose:

- **Dynamic society formation/failure.** A society hitting population zero
  just sits at its floor today, same as the existing single-settlement
  collapse behavior. Whether that should mean something more (real
  dissolution, absorption into a neighboring society) is deferred until the
  fixed-N core is actually running and there's something real to observe.
- **Explicit rivalry mechanics** (formal alliances, claims, war). Phase 3
  answered this for now: implicit contention holds up across varied seeds/
  topologies and produced at least one genuinely dramatic moment with zero
  purpose-built code, so this stays deferred — a real candidate only if
  Phase 4's highlight extraction later finds the implicit version starts
  feeling repetitive over much longer stretches than Phase 3 tested.
- **How many societies, eventually, and does the graph need to grow to fit
  them.** Same "how far does the real-ass-world scale ambition go" posture
  v2 left deferred — not a v3 build target, just something the design
  shouldn't block later.
- **Monetization.** Still explicitly deferred, unchanged from v2 — plumbing
  stays live, nothing here is a build target on its own.
