# seam

Simulated multi-agent economy. v1/v2/v3 all shipped — see `DESIGN.md`, `DESIGN-V2.md`, `DESIGN-V3.md` for build history, `ANALYSIS.md` for the live data-analysis pass, and this session's memory (`project_seam.md` in the Claude memory store) for full narrative context. This file exists so the next session's open work is visible immediately, without having to go hunting for it in memory or old commits.

## Where things stand (as of 2026-07-20)

**Both decisions from this session's external research pass are now built and verified — see `DESIGN-V3.md`'s "Phase 5" and "Research thread" sections, and `LOG.md`'s 2026-07-20 entries for the full account.**

1. **Workstream A (fixed first, was blocking accurate narrative work)**: `sidecar.py`'s narrative generation had been silently dead since v3 Phase 0 (`get_settlement()` hit a route Phase 0 removed). Fixed, verified live against real Ollama output.
2. **Workstream B — asymmetric-power campaign, run and resolved**: a real `--order-strength` tunable replaced the fixed `ORDER_GATHER_MULTIPLIER` constant; 75 runs (5 levels x 15 seeds) found trade activity declines ~21.5% from symmetric to strong asymmetry (SOVSIM-consistent), but population/survival mostly doesn't degrade (14/15 seeds: zero deaths at any level) except one seed with a sharp collapse specifically between levels 2.0-2.5. Mixed, honest result — not a clean replication either way.
3. **Workstream C — Phase 5 relationships, built and verified**: every agent now tracks real trade/contention/order-following history with specific other agents (mechanical, all tiers); a lead's LLM memory verified live referencing its actual top relationship by id.

`seam-swarm`'s own slice of the same research pass (multi-echelon command depth, the propose-validate-execute pattern) is documented in that repo's `PIVOT-NOTES.md` — still unbuilt, exploration only, untouched this session.

**Not yet done, flagged honestly rather than silently dropped**: the crowd-wide feedback aggregate ("how many distinct agents follow lead0's orders") that Phase 5's plan named as a possible next step — the per-agent data it needs now exists, but computing the aggregate itself wasn't done this session. Also open: cross-checking Phase 5's new relationship data against *why* seed 15 specifically collapsed in the asymmetry campaign (not done — both pieces just didn't exist together until today).

## Proposed next moves (2026-07-20, none started, none chosen yet)

Six real options surfaced after walking back through this session's build. Listed for the next session to pick up, not in priority order — nothing here has been decided:

1. **Finish the feedback-loop aggregate** — a lead currently has no way to see "how many *distinct* agents are actually listening to me vs. ignoring me," only individual `orders_followed` counts per relationship. Short follow-up on data that already exists (see the "not yet done" note above).
2. **Investigate why seed 15 specifically collapsed** in the asymmetric-power campaign (`LOG.md`, `core-rs/logs/asymmetric_power_campaign_2026-07-20.csv`) — collapsed sharply between order_strength 2.0 and 2.5, the only one of 15 seeds to do so. Graph topology hasn't been inspected; may be a structural bottleneck (n13-shaped) made worse by strong leader dominance.
3. **Cross-reference Phase 5 relationship data against the campaign's trade decline** — find out *whose* specific relationships eroded as `order_strength` increased (certain roles? certain pairings?). Flagged as not done in the Workstream C entry.
4. **Wire relationships into narrative/highlights** — they currently only feed a lead's private `memory_summary`; scenes and viewer highlights don't reference them yet. This is the direct path from "data exists" to the actual "watchable drama" payoff.
5. **Move `seam-swarm` from notes to a real build** — the multi-echelon command depth + propose-validate-execute pattern documented in that repo's `PIVOT-NOTES.md` were waiting on seam's own architecture maturing (real memory, a feedback channel) — that's now true.
6. **Real rivalry/conflict mechanics** — relationships currently only record trade and contention, not actual antagonism. A genuine adversarial mechanic would connect both the Watchable World ambition and `seam-swarm`'s own open questions about opposing sides.

## Viewer: full audit done, Waves 1-4 + a smoke-test harness built (2026-07-20)

**Waves 1-3 recap below; Wave 4 (relationship network graph) + WS auto-reconnect shipped in a later round the same day, live to an actually-running world** (`serve`+`sidecar.py`, port 7878, phone access over WiFi - see `LOG.md`'s final 2026-07-20 entry). Both were viewer-only changes (no backend touch), developed and verified against an isolated scratch copy, then copied over the real `viewer/index.html` once verified - the live world was never restarted, kept ticking the whole time (confirmed correct against it directly afterward, tick 42566+). Auto-reconnect: a dropped WS connection (phone locking, leaving WiFi range) now retries automatically instead of going dark permanently, verified via a deterministic Node harness rather than live Chrome (see the methodology note below). The network graph: every lead/hatch on a plain circle, edges from `top_relationships` colored by dominant relationship type and weighted by interaction count, crowd partners shown as small satellite nodes rather than dropped - the first place relationships are visible as a picture instead of scrolling text.


A full read-through of `core-rs/viewer/index.html` (previously untouched all session) found it had no path to any of this session's new backend work. Full 6-wave/11-item proposal discussed; the "stay vanilla, no React yet" call was explicitly revisited and reconfirmed (nothing in the proposal structurally needs a framework — the file's real weak point is scattered global state, not rendering complexity). Waves 1-3 plus a smoke-test harness built and verified (full account in `LOG.md`'s two 2026-07-20 viewer entries):

- **Wave 1**: consolidated seven scattered globals into one `viewerState` object — pure refactor, no behavior change.
- **Wave 2**: rendered `top_relationships` for real (leads/hatch, not just the AI's prose about it); surfaced active `scarce:`/`rich:`/`order:` signals on the map (new `Snapshot.active_signals`, `build_active_signals()` in `serve_main.rs`); wired `order_strength` into `serve` itself (was headless-only) and into the masthead.
- **Wave 3**: per-society specialization index (`StatsTracker::specialization_index` generalized to take any agent-ref iterator, `stats.rs`); real trade/craft-rate sparklines computed client-side from consecutive snapshots (a raw cumulative counter only climbs — the rate is the actual signal).
- **Smoke-test harness** (`core-rs/viewer/smoke_test.sh`) — moved up from its original later slot on purpose, so the next genuinely complex visual feature (the relationship network graph) gets a repeatable regression check. Built, then deliberately broken to confirm it actually fails — which caught three real false-positive bugs in the *test script itself* (patterns that matched unevaluated JS template source in the dumped page, not real rendered output) before they could ever hide a real regression.

**A real methodology limit surfaced along the way, worth remembering for any future viewer work**: headless-Chrome's `--virtual-time-budget` + `--dump-dom` is **not reliable** for verifying anything that depends on multiple WebSocket messages accumulating over time (confirmed the server itself pushes a fresh snapshot every ~200ms with no throttling, via a direct Python WS client — the unreliability is purely in how virtual time interacts with real network events in headless Chrome). Single-snapshot / structural checks are fine and were used throughout; multi-message accumulation logic (like the rate sparklines) needs a direct logic test instead (a Node `vm` context with stubbed `document`/`WebSocket`/`fetch`, calling `render()` with synthetic snapshots) — see `LOG.md` for the pattern.

**Still open, not built this round** — Wave 5 (historical replay against the existing Postgres layer, its own dedicated exploration+plan pass) and the remaining two-thirds of Wave 6 (fixing the shared-single-possession problem, and an actual access boundary - both gated on actual multi-viewer/outside-sharing use, not a fixed schedule, per the reasoning already recorded above).

## Where things stood as of 2026-07-19 (n13 investigation — resolved, kept for history)

**The n13 congestion-trap investigation that this file used to track is resolved.** Full account in `ANALYSIS.md`'s "Angle 6" section. Short version:

- `best_food_move_score` was null 100% of the time at n13 (confirmed across ~2.4-3.0M decisions in 3 runs) — n13's only two graph neighbors are both wood nodes, zero food within 1 hop, a fact of the graph not a scoring bug.
- The real bug: `bfs_next_hop_to_food` (`core-rs/src/decide.rs`) returned `None` unconditionally for any agent standing on *any* food node, so it never even ran for agents already at n13 — the traffic actually driving the finding. Fixed to score "stay put" as a real candidate, and dropped the old hunger≥60 gate so it runs continuously (commit `35e8218`).
- Verified, not assumed: re-ran all three instances on the fixed binary, deaths dropped to near-zero (was 100% at n13 before), n13's activity share roughly halved (64-90% → 50-53%, stable across 160k ticks). **Not fully solved** — n13 is still the single most-active node by a wide margin, just less of a trap than before (commit `58a7aef`).
- Bonus finding, cheap to get (from `stats.csv`, not the raw logs): the sidecar-vs-no-sidecar trade-count gap seen earlier this session vanished post-fix — main and nosidecar now track within 1% of each other for the whole run. Flagged as a likely correction to last session's "memory dampens trade" finding (probably confounded by the congestion trap, not a real LLM effect) — **not yet re-verified with a dedicated experiment**.

**Nothing is running right now.** All three instances (main:7878, societies4:7880, nosidecar:7881) plus both sidecars were stopped 2026-07-19 after a real disk-space near-miss (grew to 4.8GB free / 99% used overnight — the three full-logged runs were eating ~2GB/hour combined and nobody was watching). Raw JSONL from that run (42GB) and the archived pre-fix baseline (14GB) were deleted after their findings were extracted into `ANALYSIS.md` — the small `stats.csv`/`society-stats.csv`/sidecar files were kept and still exist in `core-rs/logs/`. Disk is back to ~60GB free.

## Next steps when resuming

1. **If restarting long runs again, don't repeat the disk near-miss.** These full-logged 3-society/40-agent runs eat roughly 350-450MB/hour per instance (measured directly this session, not the earlier ~18MB/hour estimate which was wrong) — three concurrent instances will fill even a large disk in well under a day. Either check in more often, or don't leave `--full-log` running unattended for 12+ hours without a plan to archive/delete.
2. **The trade-gap correction is a real open thread**: if it matters, a dedicated memory-on/off experiment on the *fixed* engine (mirroring last session's Phase 2 methodology) would confirm whether "memory dampens trade" was ever a real effect or entirely a congestion-trap artifact.
3. **n13 is reduced, not eliminated** — the natural next mechanical step (not started) is extending food-seeking lookahead past 1 hop for the ordinary (non-emergency) path, per `ANALYSIS.md` angle 6's last paragraph, if pushing past ~50% n13 share matters.
4. Everything through commit `58a7aef` is pushed to `origin/main` — check `git log` / `git push` status before assuming, this note doesn't self-update.
