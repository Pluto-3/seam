# seam — analysis strategy (the "step out of the box" pass)

This document marks a real pivot in how this project's accumulated
simulation data gets looked at, and is meant to stay live — updated as new
angles get explored, not a one-time snapshot like `LOG.md`'s dated entries.

## How this started

After the sound-logging fix (society ground-truth tagging, per-society
stats CSV) and the first controlled comparison — a societies=4 run (testing
the leaderless-society gap) and a no-sidecar run (isolating whether LLM-
driven leads change anything) — a critical-data-analysis pass answered
those two specific questions and found two real, verified results:

- No visible correlation between having a lead and a society's survival
  (`society3`, leaderless, tracked the best-performing *led* society almost
  exactly).
- A real, replicated divergence in trade volume between sidecar-driven and
  mechanical-only runs — but traced to a specific, unexplained crowd-level
  trading resurgence around tick ~37,000-41,000 that only happens with a
  sidecar attached, not a simple "leads trade more" story.

The user's reaction: not satisfied. The analysis had been scoped narrowly
around the two questions the runs were explicitly designed to test, missing
everything else three ~90,000-tick, fully-logged, multi-society runs could
actually tell us. This document is the resulting deliberate broadening —
sourced partly from the project's own unexplored data (craft economy, LLM
narrative content, spatial/node-level patterns) and partly from outside
research on how other fields analyze exactly this kind of system (agent-
based economic simulation, multi-agent population dynamics).

## The seven angles

Each one below states what it would actually teach us, not just what metric
it produces. Status is tracked per angle as work happens — this is meant to
be read again later, not just once.

### 1. Critical slowing down / early-warning signals

**Question:** every run collapsed in the same narrow window (first
1,000-2,000 ticks). Is there a detectable statistical warning — rising
variance or autocorrelation in hunger/energy — *before* the crash, or does
it happen with no precursor at all?

**Grounding:** well-established in ecology/complex-systems research — see
[Early-warning signals for critical transitions (Nature)](https://www.nature.com/articles/nature08227),
[Critical slowing down in a real physical system](https://arxiv.org/pdf/2403.17973),
[Early warning signals for critical transitions: a generalized modeling approach (PLOS Comp Bio)](https://journals.plos.org/ploscompbiol/article?id=10.1371%2Fjournal.pcbi.1002360).
Systems approaching a tipping point show weaker compensatory recovery from
perturbation, showing up as rising variance and temporal autocorrelation
before the actual collapse.

**Data status:** the periodic stats CSV (one row per 30 real seconds) is
too coarse for a crash that completes in ~2,000 ticks. `--full-log` data,
if reconstructed at tick resolution directly from the raw JSONL (every
alive agent logs one entry per tick, so population/hunger *can* be rebuilt
exactly, just not from the coarse CSV), may be fine enough — untested
until attempted.

### 2. Trade network topology (network science)

**Question:** does *position* in the trade network matter more than
anything an agent does? Directly tests the `society3` finding (no lead,
did just as well as the best led society) — is that because leadership
doesn't matter, or because home-node position in the graph dominates
outcomes regardless of behavior?

**Grounding:** [Effect of network topology and node centrality on trading (Scientific Reports)](https://www.nature.com/articles/s41598-020-68094-z)
found random/small-world trade networks produce *meritocratic* outcomes,
scale-free networks produce *topocratic* ones (position matters more than
merit) — see also
[Agent-based simulations of payoff distribution in economic networks](https://link.springer.com/article/10.1007/s13278-019-0601-y).

**Data status:** fully available now. Every trade (agent, target, tick,
success) is already in the full logs.

### 3. Wealth/resource inequality (econophysics)

**Question:** does specialization drive inequality up? Does inequality
predict who dies next, or is death random with respect to wealth?

**Data status:** fully available now. Per-agent inventory is in every
logged action's `state_after`.

### 4. The craft/tool economy

**Question:** completely unanalyzed all project. Does tool ownership
correlate with survival or gather efficiency? Is there a durable
tool-owning class vs. a tool-less underclass?

**Data status:** fully available now. `CRAFT` actions and
`tool_durability` are already logged.

### 5. What the leads actually said

**Question:** hundreds of real LLM-generated memory summaries and
decisions exist in the sidecar logs, essentially unread. Does a lead's
self-narrative match its actual mechanical performance, or is there a gap
between self-perception and reality? This is also the most direct read on
whether the sidecar produces genuinely *watchable* content — the actual
point of the v3 pivot.

**Data status:** fully available for the two sidecar-driven runs
(`sidecar/logs/decisions.jsonl`, `decisions_societies4.jsonl`). Not
available for the no-sidecar run, by design.

### 6. Node-level spatial hotspots

**Question:** every prior contention analysis has been at the *society*
level. Independent of which society claims a node as home turf — which
specific nodes are permanent hotspots, which are dead zones never visited,
and which are one-off contested moments?

**Data status:** fully available now. Location is logged on every action.

### 7. Rigorous changepoint detection

**Question:** the tick ~37,000-41,000 trading resurgence was found by
eyeballing 25-row samples of a CSV. Where does it *actually* start, down
to the tick, and does that moment coincide with anything specific (a
death, a memory update, a threshold crossing)?

**Data status:** fully available now, needs a real changepoint-detection
pass instead of visual inspection.

## Tooling decision

None of `numpy`/`networkx`/`scipy` were installed — the project's stdlib-
only policy was set for the simulation/exporters specifically (confirmed
early in the project, for iteration speed). For this offline analysis
tooling, confirmed with the user to install these rather than hand-roll
graph centrality/community detection/changepoint algorithms in pure
stdlib — faster, more reliable, doesn't touch `core-rs` or the sim's own
runtime Python at all.

## Status

Findings for each angle get appended below as the work happens, plus a
closing section on genuine data-collection gaps found along the way and
concrete pipeline improvements for future runs — not just "we didn't test
this," but what specifically would need to change to test it next time.

*(to be continued below as each angle is actually run)*

---

## Findings

### Angle 2: Trade network topology — a real, replicated, decisive answer

`analyze_trade_network.py`. Built the actual weighted trade graph for all
three runs and tested position (degree centrality) against own skill
(trade success rate) as predictors of wealth and survival, via Spearman
correlation.

**Result, consistent across all three independent runs:**

| Run | centrality → survival | own skill → survival |
|---|---|---|
| main | ρ=+0.756 (p=1.2e-09) | ρ=+0.238 (p=0.11, not significant) |
| societies4 | ρ=+0.810 (p=5.1e-12) | ρ=+0.145 (p=0.33, not significant) |
| nosidecar | ρ=+0.526 (p=1.7e-04) | ρ=**-0.383** (p=8.6e-03, significant and negative) |

**This is a topocratic economy, decisively.** Network position (how many
distinct trade partners an agent has) strongly and significantly predicts
survival in every run. An agent's own trade success rate does not — in the
no-sidecar run it's actually significantly *negatively* correlated with
survival. This directly explains the earlier `society3` finding (no lead,
survived just as well as the best led society) with an actual mechanism
instead of a shrug: it was never about leadership, it's about how
well-connected that society's home node made its agents.

Community detection (modularity-based, computed with zero knowledge of
society labels) found trade communities only partially align with society
boundaries (30-60% purity, not close to 100%) — trade communities cut
across society lines substantially, consistent with and structurally
confirming the already-known cross-society trade percentages (44%/67%/19%).

### Angle 7: Changepoint detection — the resurgence, precisely dated

`analyze_changepoints.py` (`ruptures`' PELT algorithm on a 250-tick-binned
trade-count series, penalized to avoid overfitting noise). Replaces the
earlier eyeballed "~tick 37,000-41,000" with exact, statistically-detected
transitions:

- **main**: crash-trading burst (0-1,250), quiet lull (1,250-40,000, mean
  75.5 trades/bin), then a sharp, sustained resurgence starting **exactly
  at tick 40,000** (mean 1,163.1 trades/bin) that holds all the way to the
  end of the run.
- **societies4**: same shape, resurgence starts at **tick 35,000** (1,172.1
  trades/bin — nearly identical rate to main's), but then **tapers back
  down starting at tick 57,500** to 92.8 trades/bin, close to the original
  lull rate — confirming the earlier "boom then taper" read, now precisely
  dated to a ~22,500-tick window.
- **nosidecar**: one changepoint only — the initial crash burst — then
  **flat at 6.2 trades/bin for the entire remaining 87,571 ticks**. No
  resurgence at any point in the whole run.

Caught and fixed a real bug in the script itself while running this: the
first version tracked "run length" only from trade-bearing entries, so
nosidecar's flat tail (no trades at all) made it silently report the run
as 49,835 ticks long instead of its real 88,821 — fixed to track from
every entry, not just trades, before trusting the result.

### Angle 5: What the leads actually said — one clean finding, one real methodology failure caught before trusting it

`analyze_llm_narratives.py`, run against both sidecar decision logs
(`sidecar/logs/decisions.jsonl`, `decisions_societies4.jsonl` — 36,914 real
decisions and 3,681 real memory summaries combined, one JSON parse error
from a torn write when a process was killed, skipped).

**Clean, valid finding: the LLM answered 100% of decision prompts** —
19,229/19,229 and 17,685/17,685, zero fallbacks to mechanical autopilot
across both runs. Worth noting because earlier project history recorded
the fallback path as "never once fired across ~11,000 real decisions" back
in v2 testing — now confirmed again at more than 3x that sample size,
still zero.

**The sentiment-vs-performance correlation is not trustworthy — caught,
not glossed over.** Scored each memory summary with VADER (a standard,
general-purpose sentiment lexicon) and checked it against the lead's real
`trade_success_ratio` at that moment. Before trusting a near-zero
correlation (ρ=+0.027, ρ=-0.043, neither significant), spot-checked the
"most undersold" outputs and found VADER scoring lines like *"I'm on fire,
crushing every trade and making a killing... leaving all the competition
in the dust"* at **-0.85** (strongly negative) despite it being pure
bragging at a 100% trade success rate. Verified directly with controlled
test sentences: VADER handles plain emotional language correctly ("I am
happy" → +0.70, "worried about starving" → -0.80) but systematically
misreads this project's competitive-bragging idiom — "crushing," "making a
killing," "leaving in the dust" — as negative, because its lexicon
associates those words with violence, not victory. **The correlation
numbers are an artifact of a domain-mismatched tool, not a real finding
about lead self-perception — not reported as validated.** A future pass
would need either a custom small lexicon for this project's "trash-talk"
register or an LLM-based classifier instead of a fixed-lexicon one.

### Angle 3: Wealth inequality — a genuinely equal economy, and wealth predicts survival everywhere

`analyze_inequality.py` — Gini coefficient (0=perfectly equal, 1=one agent
holds everything) on final resource holdings, per society, over time
(10,000-tick checkpoints), and against survival.

**This economy stays remarkably equal throughout** — Gini sits in a narrow
0.11-0.20 band across all ten checkpoints in all three runs, with no
runaway concentration at any point (for reference, most real-world national
economies sit at 0.3-0.6+). One real, subtle difference: nosidecar's
inequality **trends down** in its back half (0.127→0.112→0.111 from tick
40,000 to 80,000) while main/societies4 fluctuate without a clear trend —
consistent with the "trading stopped" finding from angles 2/7: with no
trade "stirring" the distribution, nosidecar's static economy mildly
equalizes over time (likely via consumption/decay) rather than staying put.

**Final wealth strongly and significantly predicts survival in every
run** (main ρ=+0.523 p=1.9e-04, societies4 ρ=+0.688 p=9.2e-08, nosidecar
ρ=+0.733 p=6.7e-09) — intuitive, but now quantified rather than assumed.
Notably strongest in nosidecar, consistent with angle 2's centrality
finding: without active lead-driven trade/orders redistributing resources,
whatever advantage an agent starts with compounds into survival more
unchecked than in the sidecar-driven runs.

### Angle 6: Node-level hotspots — the headline finding of this whole pass

`analyze_node_hotspots.py`. Independent of the society lens used everywhere
else this session: across the actual 15-node graph, **one single node,
`n13`, accounts for 42.6% (main), 64.9% (societies4), and 92.3%
(nosidecar) of all logged activity in the entire run — and literally 100%
of all deaths in every run (25/25, 26/26, 26/26) happened there and
nowhere else.** Every "contested node" finding from Phase 3/4 and every
death this whole project has been about this one node.

**First hypothesis, tested and rejected**: is `n13` simply the richest food
node? This seed has five food nodes by construction (`n1`/`n4`/`n7`/`n10`/
`n13`, resource type cycles every 3 node IDs) — checked gather stats at
all five directly. **`n13` is actually the *worst* food node by every
measure**: 11.5% gather success rate vs. 97-100% at the other four, and
the lowest average yield (2.34 vs. 6.2-8.0 elsewhere).

**Second hypothesis, also tested and rejected**: is it the most central/
best-connected node, explaining why agents end up there regardless of
resource quality (an angle-2-style topocratic story)? Reconstructed the
actual world graph from real `MOVE` actions and computed centrality —
**`n13` has low degree (2) and zero betweenness centrality**. `n2` is the
true hub (degree 7, betweenness 0.579) and is barely used by comparison.

**What this actually looks like: a self-reinforcing congestion trap, not
a rational choice.** Agents keep converging on an increasingly depleted,
low-success node instead of four clearly better alternatives just a few
hops away, and this gets *more* extreme, not less, the longer trading
stays inactive (92.3% in nosidecar vs. 42.6% in main, which trades the
most and spatially spreads out the most). The likely mechanical cause,
not yet confirmed by reading the code in this pass: `decide.rs`'s hungry-
agent pathing (`bfs_next_hop_to_food`) routes toward the *nearest* node
with any food quantity left, not the node with the best success odds —
so once `n13` becomes anyone's nearest known food option, congestion
never factors into the choice to go elsewhere. Worth a real follow-up:
this is a candidate mechanical improvement (factor current congestion
into food-seeking, not just distance/availability), not just an analysis
finding.

**Follow-up, 2026-07-17: the fix attempted from this finding didn't work,
and the real reason is now understood.** Made `bfs_next_hop_to_food`
congestion-aware (scores every reachable food node by
`congestion_factor(node) * MOVE_LOOKAHEAD_DISCOUNT^hops` instead of
returning the first one found), verified correct in isolation with new
unit tests (nearer wins when clear, farther wins when the nearer one is
congested — both pass). Live-verified against a fresh run at the same
seed/scale as the original finding: **87.6% (before) vs. 87.5% (after) —
no real change**, identical death count (23 both times). Not reported as
a fix.

Investigated why rather than move on: checked hunger levels at every
n13 action in the fixed run. **All 46 agents pass through n13, but average
hunger while acting there is 8.15 — and only 0.8% of n13's traffic happens
above the 60.0 emergency-hunger threshold** that gates the code path just
fixed. The emergency long-range BFS is a rare safety net, not what's
driving n13's dominance. The actual traffic is normal, everyday foraging —
agents arrive and *stay*, routed there by the ordinary 1-hop lookahead
(`best_local_score`/`congestion_factor` in the *existing*, already-
congestion-aware scoring path, never touched by this fix) rather than the
long-range emergency path. The real question this reframes: why does the
existing congestion discount fail to push agents toward the four
alternative food nodes even under normal (non-emergency) decision-making —
is `CONGESTION_WEIGHT` too weak, or are the alternatives simply too many
hops away for a 1-hop-lookahead decision to ever see them as competitive
with "some food chance right here"? Not yet answered — the emergency-path
fix stays in the codebase (it's a real, tested, small improvement for the
narrow case it covers) but doesn't get to claim credit for solving the
n13 problem.

**Follow-up, 2026-07-17 (same day): instrumented rather than guessed at
again.** Both hypotheses above were untestable from the existing log —
`generate_candidates`/`choose_action` computed every candidate's score
every tick and threw all but the winner away. Added `DecisionDebug`
(`decide.rs`), a per-agent-per-tick diagnostic record surfaced through a
new `choose_action_with_debug` (the original `choose_action` now just
calls it and discards the debug half — same RNG draws in the same order,
so this is behavior-preserving, confirmed by all 4 existing tests still
passing unchanged) and attached to logged entries as an enrichment field
the same way `society` already is, in both `main.rs` and `serve_main.rs`.
Carries, per decision: `gather_score` (the GATHER-here candidate),
`best_move_score`/`best_move_target` (the best MOVE anywhere),
`best_food_move_score`/`best_food_move_target` (the best MOVE
specifically toward a food-typed neighbor — the exact comparison that
tests hypothesis (b): if this is consistently `None` at n13, the better
alternatives are structurally invisible to a 1-hop lookahead, not merely
outscored), `chosen_score`, `candidate_count`, `location_occupancy`/
`location_congestion` (tests hypothesis (a): does `gather_score` still
win by a landslide even at high congestion), `hunger`, `specialty`
(closes the "specialty is never logged" gap below as a side effect, one
per-action snapshot rather than a dedicated roster record but real data
either way), and `emergency_eligible` (was this tick's routing even
subject to the fix above). Absent (not null-filled) on `DEATH` entries
and LLM-overridden lead ticks, since no candidate scoring happened for
either. Verified live on a fresh 200-tick run: the field appears on every
non-DEATH entry, a sampled GATHER-at-n14 entry showed `gather_score`
(5.26) beating `best_food_move_score` (2.25) exactly as expected, and
`analyze_node_hotspots.py` ran against the enriched log unmodified — this
is additive, not a breaking change to the log format. Not yet run against
a real n13-dominated stretch or turned into an `analyze_*.py` script —
next session's job once a longer run exists to point it at.

**Follow-up, 2026-07-18: the open question answered decisively — it's
hypothesis (b), and hypothesis (a) was never actually testable.** Three
fresh instances re-run at the original scale (seed 19, 15 nodes, 40
agents; main/societies4 with sidecar, nosidecar without), analyzed at
~150-160k ticks each via the new `analyze_decision_debug.py`. Before
trusting the two staged hypotheses, checked for a blind spot the original
diagnostic couldn't see: `generate_candidates` also scores TRADE, and
TRADE candidates are generated pairwise for every co-located agent, so a
crowded node mechanically produces far more trade opportunities than a
quiet one regardless of food quality — a structurally different
"trade-attraction trap" that `gather_score`/`best_food_move_score` alone
can't rule out. Checked directly (no new instrumentation needed, every
log entry already carries `action`): at n13 itself GATHER is 75-77% of
activity and TRADE is 0-0.7%, actually *rarer* there than the graph
average (2.6-22.1% elsewhere) — n13's share of all trades (3.9-12.0%) is
far below its share of all activity (64.3-90.2%). **Rejected. Agents at
n13 are too busy surviving to trade; this is a food/gather trap, not a
trade magnet**, confirming the original framing rather than replacing it.

With that checked, the headline reconfirmed on fresh data first, exactly
as before: n13 is 64.3% (main) / 83.2% (societies4) / 90.2% (nosidecar) of
all activity and 100% of deaths (24/24, 25/25, 26/26) in every run, and
time-windowed across the full run length (10k-tick buckets) the dominance
is sustained throughout, not easing as the population thinned from 46 to
~20-25 — so the earlier population plateau isn't agents learning to avoid
the node.

**The actual answer**: `best_food_move_score` is null **100.0% of the
time** at n13, in all three runs, across ~2.4-3.0M decisions each, every
specialty, every congestion bucket, no exceptions. Pulled n13's live
topology directly to confirm why rather than trust the log alone: **n13
has exactly two neighbors, `n2` and `n8`, and both are wood-type nodes —
zero food nodes within one hop, as a fact of the generated graph, not a
scoring outcome.** This means hypothesis (a) (`CONGESTION_WEIGHT` too
weak) was never actually a live question — there is no competing
food-move candidate for `gather_score` to out-score, at any congestion
level, so reweighting congestion cannot change this outcome. The 1-hop
lookahead structurally cannot see past n13's two wood neighbors to the
four better food nodes a few hops out.

**Real mechanical follow-up, now well-targeted instead of guessed at**:
extend food-seeking lookahead past 1 hop (2+ hops, at minimum for the
ordinary non-emergency path — the existing emergency BFS already does
long-range search but only fires at hunger≥60, covering under 1% of n13's
traffic per the prior follow-up). Not yet implemented.

**Follow-up, 2026-07-18 (same day): implemented, and this time it
actually worked — verified, not assumed.** Rereading `bfs_next_hop_to_food`
to design the fix found the real reason the *previous* fix (b3b8f0e)
measured zero change: it returned `None` unconditionally for any agent
standing on *any* food node, regardless of that node's own congestion or
quality — it never even ran for agents already at n13, the traffic
actually driving the finding. Fixed by scoring "stay put" as a real
candidate in the same congestion-discounted comparison already used for
every reachable alternative, and dropped the hunger≥60 gate entirely (it
now runs whenever food isn't already held, with influence still scaling
continuously via `hunger_pressure` rather than snapping on at a
threshold). Two new unit tests pin the actual behavior change (leaving a
congested food node for a better reachable one); all 5 tests pass.

Killed and restarted all three instances on the fixed binary, same
seed/scale, ran ~160k ticks, re-ran `analyze_decision_debug.py`.
**Real, substantial improvement, honestly checked against the same
metrics as before**: deaths collapsed to near-zero (main: 0/0, nosidecar:
0/0, societies4: 6 total and *none* at n13 — pre-fix was 24-26 deaths per
run, 100% at n13 in every case). n13's share of all activity roughly
halved: 64.3%→50.3% (main), 83.2%→52.8% (societies4), 90.2%→50.0%
(nosidecar), stable at that new level for the entire 160k-tick window,
not just an early transient. **Not oversold**: n13 is still the single
most-active node by a wide margin (50% vs. an even ~6.7% across 15
nodes) — this reduced the trap, it didn't eliminate it. `decision_debug`'s
`best_food_move_score` is *still* null 100% of the time, exactly as
expected and not a contradiction: that field only measures the old,
untouched 1-hop lookahead; the fix works through the separate BFS path,
which isn't its own field in the diagnostic, so the outcome metrics
(death count, activity share) are the real evidence here, not that
particular field.

**A second, unplanned finding, found for free from the tiny `stats.csv`
files rather than the multi-GB JSONL** — before deleting the raw
post-fix logs (56GB combined, and a real disk-space crisis had developed
by the next morning: 4.8GB free, largely from these very logs, all three
instances stopped as a result before this check happened): pulled the
`trades_cum` trajectory from each run's stats CSV instead of re-scanning
event logs. **The pre-fix sidecar-vs-no-sidecar trade gap (main 128k vs.
nosidecar 3.7k trades at matched tick counts, flagged as unexplained
earlier this session) is gone post-fix** — main and nosidecar track
within 1% of each other for the *entire* run (e.g. tick 350k: 1,028,449
vs. 1,028,922), not just at one snapshot. This strongly suggests that
gap, and by extension **last session's Phase 2 "memory dampens the
post-hunger-scare trade increase" finding, were confounded by the
congestion trap itself** rather than a genuine LLM-behavioral effect —
the no-sidecar run was so throttled by mass starvation/death that trade
never got the chance to happen anywhere else. Not re-verified with a
dedicated experiment (that would need isolating memory-on/off again,
now on the fixed engine) — flagged here as a real correction candidate,
not confirmed. `societies4` trails both (871k at tick 350k) but that's
consistent with its known 4th leaderless society, not a sidecar effect.

Raw JSONL from both the pre-fix baseline (14GB, archived) and these
post-fix runs (42GB) deleted after this write-up — the per-event
granularity they carried (n13 action-type breakdown, decision_debug
hypothesis tests, the trade trajectory above) is fully captured here and
in `stats.csv`/`society-stats.csv` (kept, tiny). Deleted under real disk
pressure (4.8GB free), not roomy hindsight - if a finer-grained
re-analysis is ever needed, it would require a fresh run.

### Angle 4: The craft/tool economy — the single strongest effect found this whole pass

`analyze_craft_economy.py`. Never analyzed before this session despite
`CRAFT` and `tool_durability` existing since v1.

**Having a durable tool is the single largest effect measured in this
entire analysis pass**: gather success rate with a tool vs. without —
95.4% vs. 11.7% (main), 88.1% vs. 10.4% (societies4), 87.5% vs. 8.3%
(nosidecar). Consistently an ~8-11x difference across all three
independent runs. This connects directly to angle 6: without-tool gather
success (8-12%) sits right next to `n13`'s overall 11.5% success rate —
consistent with most of `n13`'s crowd being toolless, and even a tool not
being enough to overcome that node's congestion.

Tool ownership itself tracked the same activity gradient as everything
else this session: 30.4% of main's agents ended the run holding a tool,
10.6% in societies4, just 2.2% (one single agent) in nosidecar — matching
each run's craft-attempt volume (304K/191K/49K) and its overall economic
activity level. Tool ownership predicted survival strongly in main
(ρ=+0.722, p=1.5e-08) and moderately in societies4 (ρ=+0.384, p=0.0077),
but wasn't significant in nosidecar (ρ=+0.170, p=0.26) — likely just
underpowered, since there was only one tool-owner total to correlate
against, not evidence tools stopped mattering there.

### Angle 1: Early-warning signals — attempted honestly, inconclusive, not a discovery

`analyze_early_warning.py`. Reconstructed a true tick-resolution (not
30-second-sampled) population/hunger series for the first 5,000 ticks of
each run directly from `full_log` — every alive agent logs one entry per
tick, so this is exact where the stats CSV was too coarse to see the
crash window at all. Tested the two classic critical-slowing-down
signatures (rising variance, rising lag-1 autocorrelation) in the lead-up
to each run's steepest decline (found at tick 1285/994/1097 respectively).

**Result: mixed, weak, not a validated finding.** Variance trend was
*negative* in two of three runs (main -0.19, nosidecar -0.17) and positive
in societies4 (+0.27) — no consistent direction. Autocorrelation trend was
positive in all three (main +0.0044, societies4 +0.0367, nosidecar
+0.0057) — directionally consistent with the theory, but tiny in magnitude
for two of the three, and each run only yields 9-12 windowed data points
to fit a trend to, which is not enough statistical power to distinguish a
real signal from noise. Reporting this as attempted-and-inconclusive
rather than either a confirmation or a refutation — the search results
that grounded this angle explicitly warned early-warning-signal
performance "depends critically on data quality... and system-specific
dynamics," and a single run each isn't enough data quality to settle it.
Would need many replicate runs at the same seed (an ensemble, not one
trajectory) to actually test this properly — see the data-collection
pipeline section below.

---

## Data collection pipeline: real gaps found, and what to do about them

Most of the seven angles turned out to be servable by data we already
had — the actual gap this pass exposed was less "we're not logging enough"
and more "we have no tooling to exploit what we log." Concretely:

### 1. Real, cheap logging gaps — both closed same-day, 2026-07-17
- ~~**Agent `specialty` is never logged.**~~ Closed as a side effect of the
  fix below: `specialty` now rides along on every `decision_debug` record.
  Still not a dedicated tick-0 roster record (would be cheaper to query
  than re-deriving it from repeated per-action snapshots), so that's a
  real remaining nice-to-have, just no longer a hard blocker for a
  specialization-vs-inequality angle.
- ~~**Crowd decision context is invisible.**~~ Closed: `decide.rs` now
  exposes `DecisionDebug` (`gather_score`, `best_move_score`/
  `best_food_move_score` and their targets, `chosen_score`,
  `candidate_count`, `location_occupancy`/`location_congestion`, `hunger`,
  `specialty`, `emergency_eligible`) per crowd/lead decision, attached to
  logged entries the same way `society` already is. Built specifically to
  make the two open hypotheses at the end of angle 6 (congestion penalty
  too weak vs. better nodes structurally invisible to a 1-hop lookahead)
  directly queryable instead of guessed at. See the angle 6 follow-up
  above for the full field list and live verification.

### 2. A real performance gap, not a data gap
Every `analyze_*.py` script this pass re-parsed the same ~1GB/2-million-
line raw JSONL from scratch (each took 25-35 real seconds; running seven
angles cost several minutes of pure redundant re-parsing). For runs this
size that's tolerable; for the multi-day runs this project's own `LOG.md`
already describes wanting, it won't be. Concrete fix: a one-time
JSONL-to-SQLite (or Parquet) conversion step after a run ends, with
society/tier/action/tick indexed — every future `analyze_*.py` becomes a
query instead of a re-parse. Not built in this pass; worth building before
the next long run rather than after.

### 3. Angle 1 specifically needs an ensemble, not more ticks
Testing early-warning signals properly needs statistical power a single
trajectory can't provide — and critically, that means **many different
seeds**, not reruns of seed 19 (a fixed seed is fully deterministic;
rerunning it produces byte-identical output, not independent samples).
This project has never had an ensemble-runner — every multi-seed
comparison this session (and Phase 3's) was manually orchestrated one run
at a time. A real `run_ensemble.py` (spin up N seeds, wait, collect logs,
feed them all through a chosen `analyze_*.py` automatically) would turn a
half-day of manual orchestration into one command.

### A design follow-up, not a data gap — flagged separately on purpose
Angle 6 surfaced something that isn't about analysis tooling at all: `n13`
looks like a genuine mechanical congestion trap (agents keep choosing an
11.5%-success node over four 97-100%-success alternatives a few hops
away). **Update, same day**: `bfs_next_hop_to_food` was made
congestion-aware and live-verified as real but insufficient (87.6% vs.
87.5%, no real change) — the actual driver is ordinary non-emergency
1-hop scoring, not the long-range path this fix touched. The new
`decision_debug` logging (above) exists specifically to make the next
attempt at this evidence-driven instead of another guess. Still the
highest-priority open item in this whole project.

## My take

The two most solid, decision-relevant findings from this pass are angle 2
(network position predicts survival, own trade skill doesn't — replicated
identically across all three independent runs) and angle 4 (tool ownership
is an 8-11x gather-success multiplier, also replicated across all three).
Both held up under real statistical testing, not just eyeballing, and both
point the same direction: **this world rewards where you are and what you
carry over anything resembling individual skill or leadership** — which
also finally explains the `society3` leaderless-society result from the
first pass with an actual mechanism instead of a shrug.

Angle 6 is the most important finding of the whole session, not just this
pass — it reframes nearly everything analyzed today (contested nodes,
deaths, the trade resurgence) as fundamentally a story about one specific
node, not a distributed multi-node economy. I'd treat fixing or at least
understanding `n13`'s congestion trap as higher priority than any further
analysis angle.

Angle 5 and angle 1 are the two honest non-findings — not failures, but
real limitations caught and reported instead of pushed past. That's
consistent with how this project has treated every other overclaimed
result all session (the Phase 0 63%→28% correction, the two
`analyze_cross_society.py` clustering bugs): a clean "we tried, the tool
or the data wasn't sufficient" is worth more than a number that looks
confident and isn't.
