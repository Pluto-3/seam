# Seam — design sketch

## Origin

Inspired by Rick Sanchez's microverse battery: a self-contained simulated world whose inhabitants live out their own lives, and whatever gets extracted (power, in the show) is a byproduct of the world running, not something the inhabitants are tasked with producing. The inhabitants here are not real people — pure simulation, no labor/consent problem.

The mined resource is data — and by extension, money, since the two are treated as convertible.

## Concept

One simulated world runs continuously. Nothing in it is "assigned a job." Value is extracted after the fact by reading the world's own history in different ways. Fun is not a tradeoff against usefulness — it's one of the lenses on the same underlying log.

## Principles

**Reuse is opportunistic, not sacred.** Fahamu, LAUA, Waypoint, Njia are accelerants because they happen to fit — not requirements. The moment integrating with one of them constrains a design decision that would otherwise push the project further, drop the integration and build the piece standalone. There is no reuse-for-reuse's-sake here.

**Document discoveries, not noise.** As the prototype gets built, real things will be learned that change the plan — dead ends, surprising emergent behavior, a mechanic that doesn't do what it was supposed to. Those go in `LOG.md`, dated, one entry per discovery. `DESIGN.md` stays a clean snapshot of current decisions; it gets edited when a decision changes, not appended to as a journal.

## Agents (three tiers)

**Crowd (cheap, many).** Hundreds to thousands of simple agents. Decisions come from a utility function over needs (energy, hunger) and the seven actions below — no reasoning, just scored choices. Cheap enough to run at population scale, which is what makes emergent patterns (who survives, what strategies work) show up statistically.

**Leads (rich, few).** A small cast — tens, not thousands — driven by actual reasoning (LLM call over memory + perception + a persistent goal/personality, e.g. "become the wealthiest trader"). Expensive per-agent, affordable because there are few.

**Player character (the hatch).** Same interface as a lead — same action set, same character sheet — but the decision source can switch between autopilot (simple policy, like the crowd) and direct player input. Defaults to autopilot; the player can "open the hatch" and take over at will, then hand control back.

**Cross-tier interaction:** leads can issue standing orders that bias how nearby crowd agents score their actions ("everyone gather wood"). Crowd behavior aggregates back up as something leads notice and react to ("wood is scarce"). This is what keeps the fun layer causally connected to the mining layer instead of being cosmetic.

## World shape

Not a grid. A graph underneath — nodes are meaningful places (resource sites, settlements), edges are routes with a travel cost — same shape Njia already reasons about for freight routing, so there's real routing logic to lean on, not just a similar concept.

Movement along that graph is rendered continuously and in real time, not tile-by-tile. That's what makes the world watchable and makes the player's hatch character controllable in a way that actually feels good, rather than snapping between grid cells.

The crowd doesn't need full individual rendering to get this — only the leads and the player character need to look and move like real characters. The crowd is still simulated per-agent (each one really has its own state and makes its own decisions — trade and signaling require that), it's just not individually drawn in detail, the way an RTS shows a mass of units cheaply without giving each one full physics. "Cheap" here means cheap to render and cheap to compute per tick, not cheap in ambition.

## World mechanics

- **Resource:** a node has a type, quantity, and regen rate. Raw resources (ore, food) vs. refined resources (tools) via crafting — the raw/refined split is what produces an actual economy instead of pure foraging.
- **Goal:** for the crowd, a utility function (maximize survival / wealth). For leads and the player, a persistent objective plus personality.
- **Tick:** world state updates (regen, events) → every agent perceives local state → every agent (or the player) picks an action → actions resolve → the tick is logged as `(agent_id, tier, state_before, action, state_after, delta)`.

That log line is the only thing the simulation actually produces. Everything downstream reads it.

## Actions

The minimal set that still lets a real economy emerge, not just foraging:

- **Move** — travel along the graph toward a node.
- **Gather** — take a raw resource from a node (bounded by its regen rate — this is the scarcity).
- **Consume** — use a resource to satisfy a need (eat food so hunger doesn't kill you).
- **Trade** — hand a resource to a nearby agent in exchange for one of theirs.
- **Rest** — recover energy, at the cost of time not spent gathering.
- **Craft** — combine raw resources into a refined one (e.g. wood + ore → tool). Turns barter into supply chains — this is where real strategic depth lives, and where the strategy exporter gets multi-step signal instead of trivial single-step trades.
- **Signal** — drop a marker at a node ("food here," "route overworked") and sense nearby markers left by others. No reasoning required, cheap to run at crowd scale, and it produces genuine emergent route-finding (stigmergy — how ant colonies find efficient paths with no central planning). This is the action most directly relevant to Waypoint.

Deliberately not included yet: currency/pricing and property/territory. Both are real and would add depth, but each is a heavier commitment (a market needs a clearing mechanism, property needs enforcement) — worth adding once trade + craft + signal prove the core loop is good, not before.

## The three exporters (read the same log, three ways)

1. **Strategy exporter** — evaluates which crowd utility-weightings survived longest / accumulated most, exports winning parameter sets as candidate policies. Natural feed into Waypoint.
2. **Data exporter** — raw (state, action, outcome) trajectories as a versioned dataset. Standalone sellable/usable asset.
3. **Narrative exporter** — filters lead-tier events (deaths, trades, rivalries, notable decisions) into a readable feed. The spectacle layer — not a separate simulation, just a different filter over the same log.

## Fit with existing stack

- **Fahamu** (RAG + agent core) — natural fit for the lead-tier agent brains.
- **LAUA** (local autonomous agent) — natural fit for the process that runs the sim in the background and triggers exports.
- **Waypoint** (behavioral/planning intelligence) — natural consumer of the strategy exporter's output.

The genuinely new build is the world/tick engine and the crowd-tier decision logic. Everything else is reuse.

## Build plan

Skipping a formal SRS — this is solo and still fluid, a requirements doc would be stale the moment the prototype changes it. Phased instead, each phase only starting once the one before it proves worth continuing:

- **Phase 0 — headless mechanic test. DONE, 2026-07-15.** No rendering, no leads, no player, no exporters. A small graph (tens of nodes), a small crowd (tens of agents) running move/gather/consume/trade/rest/craft/signal, fast-forwarded (not real-time — run as many ticks as compute allows) with summary stats printed every N ticks (population, average resources held, trade volume, most-used routes). Answer: **yes** — scarcity + specialization produces real, growing trade, confirmed by a negative control (specialization index 0.27 without trade vs. 0.42-0.54 with it, across seeds) and a hand-traceable small run. Full story, including two bugs found along the way, in `LOG.md`. Open follow-ups before Phase 1: population sustainability is seed-sensitive, food accumulation is currently unbounded, and the signal→routing feedback loop is disabled pending a non-flat scoring design.
- **Phase 1 — real-time rendering.** Once Phase 0 shows the mechanic is alive, put a real-time view on top of the same graph so it's watchable.
- **Phase 2 — leads + the hatch.** Add the small reasoning-driven cast and the player-controllable character.
- **Phase 3 — the three exporters.** Strategy, data, and narrative exporters wired up, plus whatever integration with Fahamu/LAUA/Waypoint still makes sense at that point (per the reuse principle above — only if it still fits).

## Open questions

Resolved: world shape (graph + continuous rendering, see above), action set (see Actions above).

Still open, need a call before Phase 0 can start:

- **Language/runtime.** Recommendation: Python for Phase 0. Iteration speed matters more than raw performance while we're still testing whether the mechanic is even interesting — population-scale performance is a Phase-0-proven, not Phase-0-assumed, problem. If Python turns out to be the bottleneck once we're actually pushing scale, that's a deliberate rewrite of just the crowd tier at that point, not a decision to pre-optimize for now.
- **Scale target for Phase 0.** Recommendation: deliberately small — tens of agents, a graph of ~10-20 nodes — specifically so behavior is easy to inspect by hand. Scale up geometrically once the mechanic is confirmed worth scaling.
- **Rendering engine** (needed by Phase 1, not Phase 0) — not yet decided.
- **LLM backend for leads** (needed by Phase 2, not Phase 0) — Fahamu is the obvious first try, per the reuse principle it gets dropped if it doesn't fit cleanly.
