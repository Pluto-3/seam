# seam

Simulated multi-agent economy. v1/v2/v3 all shipped — see `DESIGN.md`, `DESIGN-V2.md`, `DESIGN-V3.md` for build history, `ANALYSIS.md` for the live data-analysis pass, and this session's memory (`project_seam.md` in the Claude memory store) for full narrative context. This file exists so the next session's open work is visible immediately, without having to go hunting for it in memory or old commits.

## Next steps when resuming (as of 2026-07-17)

**Nothing is running right now.** All `serve`/sidecar instances were killed at the end of the last session. You (the user) said you'd restart them personally once you're back — this file assumes that hasn't happened yet.

The open investigation, in order:

1. **Restart the simulation run(s)** — whatever config you want (previous session used `main`/`societies4`/`nosidecar` variants on ports 7878/7880/7881). Use `--log-path --full-log --stats-csv --society-stats-csv` every time — a past session lost 11 hours of data by forgetting `--log-path`.
2. **Let it run long enough for the congestion trap to actually develop.** A quick 200-tick test only showed node `n13` at 19.2% of activity; the real finding (42–92% of all activity, 100% of deaths) only showed up over 90,000-tick / multi-hour runs. Don't try to answer the open question below from a short run.
3. **Pull the new `decision_debug` field from the log, specifically for ticks where agents are at `n13`.** This field was added and verified working (mechanism confirmed, not yet used for real analysis) in commit `b8000ad`. Check:
   - Does `gather_score` beat `best_food_move_score` even when `location_congestion` is high? → if yes, `CONGESTION_WEIGHT` (currently 0.3, in `constants.rs`) is too weak relative to hunger-scaled food value.
   - Is `best_food_move_score` usually `null` at `n13`? → if yes, no food node is even 1 hop away, meaning the normal decision-making literally cannot see the better alternatives a few hops out — the fix would need to extend lookahead depth, not just reweight congestion.
   - There's no `analyze_*.py` script for this yet — writing one (reading `decision_debug` from the JSONL, filtering to `n13` or wherever the hotspot lands this run) is the next real piece of tooling needed, following the pattern of the existing `analyze_node_hotspots.py` etc.
4. **Full context**: `ANALYSIS.md`'s "Angle 6" section has the whole story — the original hotspot finding, the emergency-routing fix that was tried and honestly verified as *not* fixing it (87.6% → 87.5%, no real change), and the reasoning behind what `decision_debug` was built to test.
5. **Housekeeping**: disk was last checked at 62GB free, not rechecked this session — worth a quick check early, given ~18MB/hour per full-logged run.

Everything through commit `b8000ad` is pushed to `origin/main`. No uncommitted work, no open plan file relevant beyond what's described above.
