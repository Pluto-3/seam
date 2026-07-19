# seam

Simulated multi-agent economy. v1/v2/v3 all shipped — see `DESIGN.md`, `DESIGN-V2.md`, `DESIGN-V3.md` for build history, `ANALYSIS.md` for the live data-analysis pass, and this session's memory (`project_seam.md` in the Claude memory store) for full narrative context. This file exists so the next session's open work is visible immediately, without having to go hunting for it in memory or old commits.

## Where things stand (as of 2026-07-19)

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
