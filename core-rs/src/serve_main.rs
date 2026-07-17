//! Phase 1: the persistent simulation service. The world ticks continuously
//! in a background task, independent of whether anyone is watching. Viewers
//! connect over WebSocket for a live push feed, or hit /state once over
//! REST, and can disconnect/reconnect without affecting the sim underneath.

use std::collections::HashMap;
use std::env;
use std::io::Write;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use axum::extract::ws::{Message, WebSocket, WebSocketUpgrade};
use axum::extract::{Path, State};
use axum::http::StatusCode;
use axum::response::{Html, IntoResponse};
use axum::routing::{get, post};
use axum::{Json, Router};
use rand::SeedableRng;
use rand_chacha::ChaCha8Rng;
use serde::{Deserialize, Serialize};
use tokio::sync::broadcast;

use seam_core::agents::{spawn_leads_at, AgentState, LEAD_GOALS};
use seam_core::decide::{generate_candidates, Intent};
use seam_core::log::JsonlWriter;
use seam_core::stats::StatsTracker;
use seam_core::tick::run_tick;
use seam_core::world::{generate_world, ResourceType, World};

struct Args {
    agents: usize,
    nodes: usize,
    seed: u64,
    tick_ms: u64,
    port: u16,
    no_trade: bool,
    log_path: Option<String>,
    stats_csv: Option<String>,
    stats_every_secs: u64,
    full_log: bool,
    postgres_url: Option<String>,
    run_id: Option<String>,
    societies: usize,
    // Cheap, opt-in per-society population/health trend over time - a
    // long unattended run without this has no way to reconstruct when
    // each society actually declined, only a before/after snapshot.
    society_stats_csv: Option<String>,
}

fn parse_args() -> Args {
    let mut a = Args {
        agents: 40,
        nodes: 15,
        seed: 42,
        tick_ms: 200,
        port: 7878,
        no_trade: false,
        log_path: None,
        stats_csv: None,
        stats_every_secs: 30,
        full_log: false,
        postgres_url: None,
        run_id: None,
        // v3 Phase 0: matches LEAD_GOALS.len() so the default case gives
        // every society exactly one lead with no new goals/personalities
        // needed yet.
        societies: 3,
        society_stats_csv: None,
    };
    let argv: Vec<String> = env::args().collect();
    let mut i = 1;
    while i < argv.len() {
        match argv[i].as_str() {
            "--agents" => {
                a.agents = argv[i + 1].parse().expect("--agents must be an integer");
                i += 2;
            }
            "--nodes" => {
                a.nodes = argv[i + 1].parse().expect("--nodes must be an integer");
                i += 2;
            }
            "--seed" => {
                a.seed = argv[i + 1].parse().expect("--seed must be an integer");
                i += 2;
            }
            "--tick-ms" => {
                a.tick_ms = argv[i + 1].parse().expect("--tick-ms must be an integer");
                i += 2;
            }
            "--port" => {
                a.port = argv[i + 1].parse().expect("--port must be an integer");
                i += 2;
            }
            "--no-trade" => {
                a.no_trade = true;
                i += 1;
            }
            "--log-path" => {
                a.log_path = Some(argv[i + 1].clone());
                i += 2;
            }
            "--stats-csv" => {
                a.stats_csv = Some(argv[i + 1].clone());
                i += 2;
            }
            "--stats-every-secs" => {
                a.stats_every_secs = argv[i + 1].parse().expect("--stats-every-secs must be an integer");
                i += 2;
            }
            "--full-log" => {
                a.full_log = true;
                i += 1;
            }
            "--postgres-url" => {
                a.postgres_url = Some(argv[i + 1].clone());
                i += 2;
            }
            "--run-id" => {
                a.run_id = Some(argv[i + 1].clone());
                i += 2;
            }
            "--societies" => {
                a.societies = argv[i + 1].parse().expect("--societies must be an integer");
                i += 2;
            }
            "--society-stats-csv" => {
                a.society_stats_csv = Some(argv[i + 1].clone());
                i += 2;
            }
            other => {
                eprintln!("unknown arg: {other}");
                i += 1;
            }
        }
    }
    a
}

#[derive(Serialize, Clone)]
struct Snapshot {
    tick: i64,
    population: usize,
    total: usize,
    avg_energy: f64,
    avg_hunger: f64,
    specialization_index: f64,
    trades_cumulative: u64,
    uptime_secs: u64,
    leads: Vec<serde_json::Value>,
    societies: Vec<serde_json::Value>,
    // v3 Phase 1: which society's hatch /player/action currently controls -
    // purely additive so a future viewer can show "currently yours" vs.
    // autopilot without a second round-trip.
    possessed_society: String,
    narrative: Vec<serde_json::Value>,
    events: Vec<serde_json::Value>,
    // v3 Phase 4: a separate feed from `events`, not folded into it - found
    // during verification that routine "order" events (also lead/hatch-tier,
    // frequent under scarcity) were flooding the shared 30-slot cap and
    // evicting cross-society highlights before a human ever saw one. Kept
    // small and separate so the rarer, more interesting moments don't have
    // to compete with routine activity for the same slots.
    highlights: Vec<serde_json::Value>,
    // Viewer pass: which societies are present at each occupied node, right
    // now - a node is contested exactly when societies.len() > 1. Only
    // nodes with 1+ living agents are included, keeping this small.
    node_occupancy: Vec<serde_json::Value>,
}

const SETTLEMENT_ROSTER_SIZE: usize = 8;
const NARRATIVE_FEED_CAP: usize = 20;
const EVENTS_FEED_CAP: usize = 30;
const HIGHLIGHTS_FEED_CAP: usize = 20;
// v3 Phase 4: found during verification that one recurring trade pair
// (a hatch parked near a border, repeatedly trading with the same one or
// two crowd members) can monopolize the entire highlights feed - correct
// detections, but not a "highlight" repeated fifteen times. Same cooldown
// concept as decide.rs's SIGNAL_COOLDOWN/can_signal, applied to a trading
// pair instead of a signal kind.
const CROSS_TRADE_HIGHLIGHT_COOLDOWN: i64 = 300;

/// v3 Phase 0: one of these per society instead of one hardcoded settlement.
/// Generalizes what Phase 3 (v2) built - a home node, a fixed roster of
/// crowd agents, and (new) its own hatch - across N independent groups on
/// the same shared world/graph rather than just one.
struct Society {
    id: String,
    home_node: String,
    roster: Vec<String>,
    hatch_id: String,
    // v3 Phase 2: spawn_leads_at already pairs lead i with society i by
    // construction, but that pairing previously existed only as an
    // ordering convention, never stored as data - None if a society ends
    // up without a lead (possible if --societies exceeds LEAD_GOALS.len(),
    // a case Phase 0 already left as a known limitation).
    lead_id: Option<String>,
}

struct SimState {
    world: World,
    agents: Vec<AgentState>,
    rng: ChaCha8Rng,
    tick: i64,
    stats: StatsTracker,
    trade_enabled: bool,
    // v3 Phase 0: N independent societies on the same shared world, each
    // with its own home node, roster, and hatch - replaces the single
    // settlement_node/settlement_roster fields from v2 Phase 3.
    societies: Vec<Society>,
    // v3 Phase 1: a single reassignable pointer, not N simultaneously-
    // controlled hatches - defaults to societies[0].id at construction so
    // today's exact behavior (society 0's hatch controllable) is unchanged
    // until the operator actually switches via POST /player/possess/:id.
    possessed_society: String,
    // Populated by POST /leads/:id/intent (the sidecar) or POST /player/action
    // (the hatch, straight from the viewer) - drained (one-shot) into
    // run_tick's external_intents each tick, mirrors v1's "a fresh decision
    // waiting uses it for exactly one tick" semantics either way.
    pending_intents: HashMap<String, Intent>,
    // Default: lead-tier + DEATH entries only, never the crowd's own
    // gather/move/rest noise - a long unattended run would otherwise burn
    // disk fast for data nobody's actually going to read (see LOG.md).
    // full_log opts into logging every tier, once disk headroom allows it.
    log_writer: Option<JsonlWriter>,
    full_log: bool,
    // Opt-in, cheap: one row per society every stats_every_secs, reusing
    // build_society_view - a population/health trend over time that costs
    // almost nothing, independent of whether --full-log or Postgres are on.
    society_stats_csv: Option<std::fs::File>,
    stats_every_secs: u64,
    last_stats_write: std::time::Instant,
    // Phase 4: periodic scene-writing from the sidecar, capped rolling feed -
    // read-only from the sim's own perspective, just a place to keep what's
    // been written so far for the viewer and for the sidecar's own next
    // prompt (continuity between scenes).
    narrative_feed: std::collections::VecDeque<serde_json::Value>,
    // Deaths and standing orders were previously invisible in the live view -
    // only inferable from population silently dropping. A terse rolling feed,
    // built straight from each tick's own entries, no separate bookkeeping.
    notable_events: std::collections::VecDeque<serde_json::Value>,
    // v3 Phase 4: cross-society highlights, kept separate from
    // notable_events so routine order/death traffic can't crowd them out.
    highlights: std::collections::VecDeque<serde_json::Value>,
    // v3 Phase 4: last tick a given (agent, target) pair - normalized,
    // order doesn't matter - produced a cross_trade highlight. Prevents one
    // recurring relationship from monopolizing the whole highlights feed.
    cross_trade_cooldowns: HashMap<(String, String), i64>,
}

struct AppState {
    sim: Mutex<SimState>,
    tx: broadcast::Sender<Snapshot>,
    started_at: std::time::Instant,
    // Phase 5: additive, not a replacement for the JSONL log_writer above -
    // None when --postgres-url isn't passed, zero behavior change either way.
    pg: Option<Arc<tokio_postgres::Client>>,
    run_id: String,
}

struct PgEventRow {
    tick: i64,
    agent_id: String,
    tier: String,
    specialty: Option<String>,
    action: String,
    target: Option<String>,
    success: bool,
    state_before: serde_json::Value,
    state_after: serde_json::Value,
    delta: serde_json::Value,
}

struct PgLeadMemRow {
    lead_id: String,
    memory_summary: String,
    caution_bias: f64,
    trade_success_ratio: Option<f64>,
    hunger_scares_witnessed: i32,
}

struct PgSettlementRow {
    node: String,
    population_alive: i32,
    roster_size: i32,
    avg_energy: f64,
    avg_hunger: f64,
    total_food_held: f64,
}

/// Writes to Postgres happen here, after the sim lock is already released -
/// a std::sync::MutexGuard can't be held across an .await, so everything
/// that needs persisting is extracted into plain owned rows first (see the
/// tick loop above) and the actual database calls all happen down here.
async fn persist_tick(
    pg: &tokio_postgres::Client,
    run_id: &str,
    tick: i64,
    events: Vec<PgEventRow>,
    lead_memory: Vec<PgLeadMemRow>,
    settlements: Vec<PgSettlementRow>,
) {
    for e in events {
        let _ = pg.execute(
            "INSERT INTO events (run_id, tick, agent_id, tier, specialty, action, target, success, state_before, state_after, delta)
             VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)",
            &[&run_id, &e.tick, &e.agent_id, &e.tier, &e.specialty, &e.action, &e.target, &e.success, &e.state_before, &e.state_after, &e.delta],
        ).await;
    }

    let ts = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_secs() as i64;

    for m in lead_memory {
        let _ = pg.execute(
            "INSERT INTO lead_memory_snapshots (run_id, tick, lead_id, memory_summary, caution_bias, trade_success_ratio, hunger_scares_witnessed, ts)
             VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
            &[&run_id, &tick, &m.lead_id, &m.memory_summary, &m.caution_bias, &m.trade_success_ratio, &m.hunger_scares_witnessed, &ts],
        ).await;
    }

    // v3 Phase 0: one row per society instead of one total - the schema's
    // `node` column already differs per society so rows stay distinguishable
    // without a schema change; a dedicated society-id column is left to
    // whichever later phase actually needs to query per-society history.
    for s in settlements {
        let _ = pg.execute(
            "INSERT INTO settlement_snapshots (run_id, tick, node, population_alive, roster_size, avg_energy, avg_hunger, total_food_held, ts)
             VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)",
            &[&run_id, &tick, &s.node, &s.population_alive, &s.roster_size, &s.avg_energy, &s.avg_hunger, &s.total_food_held, &ts],
        ).await;
    }
}

/// Raw numbers only, deliberately no composite score - population, average
/// hunger/energy of this one society's own roster, how much food they
/// collectively have on hand, and its own hatch's state. Nothing invented
/// or weighted. Same shape v2 Phase 3 used for the single settlement, now
/// called once per society instead of once total.
fn build_society_view(sim: &SimState, society: &Society) -> serde_json::Value {
    let roster: Vec<&AgentState> = sim.agents.iter().filter(|a| society.roster.contains(&a.id)).collect();
    let alive: Vec<&&AgentState> = roster.iter().filter(|a| a.alive).collect();
    let population_alive = alive.len();
    let roster_size = roster.len();
    let avg_energy = if population_alive > 0 { alive.iter().map(|a| a.energy).sum::<f64>() / population_alive as f64 } else { 0.0 };
    let avg_hunger = if population_alive > 0 { alive.iter().map(|a| a.hunger).sum::<f64>() / population_alive as f64 } else { 0.0 };
    let total_food_held: f64 = alive.iter().map(|a| a.held(ResourceType::Food)).sum();
    let hatch = sim.agents.iter().find(|a| a.id == society.hatch_id).map(|a| a.public_view());
    // Viewer pass: resolved roster members ("who's actually here"), not just
    // a count - same cost as the population_alive/avg_energy computation
    // above, since `roster` is already the resolved Vec<&AgentState>.
    let roster_view: Vec<serde_json::Value> = roster.iter().map(|a| serde_json::json!({
        "id": a.id, "display_name": a.display_name, "alive": a.alive,
    })).collect();
    serde_json::json!({
        "id": society.id,
        "node": society.home_node,
        "roster_size": roster_size,
        "roster": roster_view,
        "population_alive": population_alive,
        "avg_energy": avg_energy,
        "avg_hunger": avg_hunger,
        "total_food_held": total_food_held,
        "hatch": hatch,
        "lead_id": society.lead_id,
    })
}

/// Viewer pass: per-occupied-node society presence, for the map's live
/// contention highlighting. Reuses society_of (Phase 4) - a node is
/// contested exactly when 2+ distinct real societies are both present.
fn build_node_occupancy(sim: &SimState) -> Vec<serde_json::Value> {
    let mut by_node: HashMap<String, (i32, std::collections::HashSet<String>)> = HashMap::new();
    for a in sim.agents.iter().filter(|a| a.alive) {
        let entry = by_node.entry(a.location.clone()).or_insert_with(|| (0, std::collections::HashSet::new()));
        entry.0 += 1;
        if let Some(soc) = society_of(sim, &a.id) {
            entry.1.insert(soc.id.clone());
        }
    }
    by_node.into_iter().map(|(node, (total, societies))| {
        serde_json::json!({
            "node": node,
            "total": total,
            "societies": societies.into_iter().collect::<Vec<_>>(),
        })
    }).collect()
}

fn build_snapshot(sim: &SimState, started_at: std::time::Instant) -> Snapshot {
    let alive: Vec<&AgentState> = sim.agents.iter().filter(|a| a.alive).collect();
    let population = alive.len();
    let total = sim.agents.len();
    let avg_energy = if population > 0 { alive.iter().map(|a| a.energy).sum::<f64>() / population as f64 } else { 0.0 };
    let avg_hunger = if population > 0 { alive.iter().map(|a| a.hunger).sum::<f64>() / population as f64 } else { 0.0 };
    let leads: Vec<serde_json::Value> = sim.agents.iter().filter(|a| a.tier == "lead").map(|a| a.public_view()).collect();
    let societies: Vec<serde_json::Value> = sim.societies.iter().map(|s| build_society_view(sim, s)).collect();
    Snapshot {
        tick: sim.tick,
        population,
        total,
        avg_energy,
        avg_hunger,
        specialization_index: sim.stats.specialization_index(&sim.agents),
        trades_cumulative: sim.stats.cumulative_trades(),
        uptime_secs: started_at.elapsed().as_secs(),
        leads,
        societies,
        possessed_society: sim.possessed_society.clone(),
        narrative: sim.narrative_feed.iter().cloned().collect(),
        events: sim.notable_events.iter().cloned().collect(),
        highlights: sim.highlights.iter().cloned().collect(),
        node_occupancy: build_node_occupancy(sim),
    }
}

#[tokio::main]
async fn main() {
    let a = parse_args();

    let mut rng = ChaCha8Rng::seed_from_u64(a.seed);
    let world = generate_world(a.nodes, &mut rng);
    let mut agents = seam_core::agents::spawn_agents(a.agents, &world, &mut rng);

    // v3 Phase 0: N societies instead of one hardcoded settlement. Each gets
    // a home node spread out by real graph hop-distance (not just index
    // order in node_order, which could leave two societies right next to
    // each other), a fixed roster of crowd agents relocated there so it's
    // guaranteed to actually have inhabitants (same reasoning v2 Phase 3
    // used for the single settlement), one lead starting there, and its own
    // hatch.
    let home_nodes = world.pick_spread_nodes(a.societies);
    let mut lead_locations: Vec<String> = Vec::new();
    let mut societies: Vec<Society> = Vec::new();
    let mut claimed: std::collections::HashSet<String> = std::collections::HashSet::new();

    for (i, home_node) in home_nodes.iter().enumerate() {
        let mut roster: Vec<String> = Vec::new();
        for agent in agents
            .iter_mut()
            .filter(|a| a.tier == "crowd" && !claimed.contains(&a.id))
            .take(SETTLEMENT_ROSTER_SIZE)
        {
            agent.location = home_node.clone();
            roster.push(agent.id.clone());
        }
        for id in &roster {
            claimed.insert(id.clone());
        }
        lead_locations.push(home_node.clone());

        // The hatch - one player-controlled agent per society. Starting
        // stats deliberately fixed, not randomized: same reasoning v2 Phase
        // 3 used - it's a single special agent, not part of spawn_agents'
        // statistical distribution.
        let hatch_id = format!("hatch{i}");
        let hatch_specialty = seam_core::world::RAW_RESOURCES[i % seam_core::world::RAW_RESOURCES.len()];
        agents.push(AgentState::new_player(hatch_id.clone(), home_node.clone(), 80.0, 20.0, hatch_specialty));

        // spawn_leads_at (called once, below, after this loop) pairs lead i
        // with society i by construction - only the first LEAD_GOALS.len()
        // societies actually get one, same known limitation noted there.
        let lead_id = if i < LEAD_GOALS.len() { Some(format!("lead{i}")) } else { None };

        societies.push(Society {
            id: format!("society{i}"),
            home_node: home_node.clone(),
            roster,
            hatch_id,
            lead_id,
        });
    }

    // One lead per society, starting at that society's home node - only the
    // first LEAD_GOALS.len() societies get a lead this way (matches the
    // default society count exactly; a known limitation if --societies is
    // ever raised past that without also adding more lead goals).
    agents.extend(spawn_leads_at(&lead_locations, &mut rng));

    println!(
        "v3 Phase 0: spawned {} societies: {}",
        societies.len(),
        societies.iter().map(|s| format!("{}@{} (roster {})", s.id, s.home_node, s.roster.len())).collect::<Vec<_>>().join(", ")
    );

    if let Some(path) = &a.log_path {
        if let Some(parent) = std::path::Path::new(path).parent() {
            if !parent.as_os_str().is_empty() {
                std::fs::create_dir_all(parent).expect("cannot create log directory");
            }
        }
    }
    if let Some(path) = &a.stats_csv {
        if let Some(parent) = std::path::Path::new(path).parent() {
            if !parent.as_os_str().is_empty() {
                std::fs::create_dir_all(parent).expect("cannot create stats directory");
            }
        }
    }

    // v3 Phase 1: defaults to society 0 - preserves the exact pre-Phase-1
    // behavior (society 0's hatch is the one /player/action controls) until
    // the operator actually calls POST /player/possess/:society_id.
    let possessed_society = societies[0].id.clone();

    let society_stats_csv = a.society_stats_csv.as_deref().map(|p| {
        let mut f = std::fs::File::create(p).expect("cannot create society stats csv");
        writeln!(f, "tick,ts,society_id,node,population_alive,roster_size,avg_energy,avg_hunger,total_food_held")
            .expect("write society stats csv header");
        f
    });

    let sim = SimState {
        world,
        agents,
        rng,
        tick: 0,
        stats: StatsTracker::new(a.stats_csv.as_deref()),
        trade_enabled: !a.no_trade,
        societies,
        possessed_society,
        pending_intents: HashMap::new(),
        log_writer: a.log_path.as_deref().map(JsonlWriter::new),
        full_log: a.full_log,
        society_stats_csv,
        stats_every_secs: a.stats_every_secs,
        last_stats_write: std::time::Instant::now(),
        narrative_feed: std::collections::VecDeque::new(),
        notable_events: std::collections::VecDeque::new(),
        highlights: std::collections::VecDeque::new(),
        cross_trade_cooldowns: HashMap::new(),
    };

    let run_id = a.run_id.clone().unwrap_or_else(|| {
        format!("run-{}", std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_secs())
    });

    let pg = match &a.postgres_url {
        Some(url) => {
            let (client, connection) = tokio_postgres::connect(url, tokio_postgres::NoTls)
                .await
                .expect("could not connect to postgres - check --postgres-url");
            tokio::spawn(async move {
                if let Err(e) = connection.await {
                    eprintln!("postgres connection error: {e}");
                }
            });
            println!("connected to postgres, run_id={run_id}");
            Some(Arc::new(client))
        }
        None => None,
    };

    let (tx, _rx) = broadcast::channel(32);
    let state = Arc::new(AppState { sim: Mutex::new(sim), tx: tx.clone(), started_at: std::time::Instant::now(), pg, run_id });

    {
        let state = state.clone();
        let tick_ms = a.tick_ms;
        tokio::spawn(async move {
            loop {
                let mut pg_events: Vec<PgEventRow> = Vec::new();
                let mut pg_lead_memory: Vec<PgLeadMemRow> = Vec::new();
                let mut pg_settlements: Vec<PgSettlementRow> = Vec::new();

                let snap = {
                    let mut guard = state.sim.lock().unwrap();
                    let sim: &mut SimState = &mut guard;
                    sim.tick += 1;
                    let trade_enabled = sim.trade_enabled;
                    let tick = sim.tick;
                    let due_intents = std::mem::take(&mut sim.pending_intents);
                    let (entries, decision_debug) =
                        run_tick(tick, &mut sim.world, &mut sim.agents, &mut sim.rng, trade_enabled, &due_intents, true);
                    sim.stats.consume(&entries);

                    // Deaths and standing orders were previously invisible in the
                    // live view - only inferable from population silently
                    // dropping a number. Built straight from this tick's own
                    // entries, no separate bookkeeping needed.
                    for e in &entries {
                        let name = sim.agents.iter().find(|a| a.id == e.agent_id)
                            .and_then(|a| a.display_name.clone()).unwrap_or_else(|| e.agent_id.clone());
                        if e.action == "DEATH" {
                            // Unconditional, unchanged from before Phase 4 - the
                            // main events feed's job of tracking every death
                            // (population awareness) shouldn't depend on whether
                            // this specific one also qualifies as a highlight.
                            sim.notable_events.push_back(serde_json::json!({
                                "tick": e.tick, "kind": "death", "agent_id": e.agent_id, "display_name": name,
                            }));
                            // v3 Phase 4: additionally, a death away from the
                            // dying agent's own society's home node is a real
                            // highlight - pushed to the separate highlights feed,
                            // not instead of the plain death entry above.
                            let location = e.state_after["location"].as_str().unwrap_or("").to_string();
                            let own_society = society_of(sim, &e.agent_id);
                            let foreign_society = sim.societies.iter().find(|s| {
                                s.home_node == location && own_society.map(|o| o.id != s.id).unwrap_or(true)
                            });
                            if let Some(foreign) = foreign_society {
                                sim.highlights.push_back(serde_json::json!({
                                    "tick": e.tick, "kind": "foreign_death", "agent_id": e.agent_id, "display_name": name,
                                    "society": own_society.map(|s| s.id.clone()), "foreign_society": foreign.id,
                                }));
                            }
                        // "player" tier catches any society's hatch, not just one -
                        // avoids hardcoding a single hatch id now that there are N.
                        } else if e.action == "SIGNAL" && (e.tier == "lead" || e.tier == "player") {
                            if let Some(kind) = e.target.as_deref().and_then(|t| t.strip_prefix("order:")) {
                                let location = e.state_after["location"].as_str().unwrap_or("").to_string();
                                sim.notable_events.push_back(serde_json::json!({
                                    "tick": e.tick, "kind": "order", "agent_id": e.agent_id, "display_name": name,
                                    "resource": kind, "location": location,
                                }));
                            }
                        // v3 Phase 4: only a lead/hatch's own trade counts - the
                        // same curation the SIGNAL gate above already relies on.
                        // Cross-society trade is common (~30% of all trades, per
                        // Phase 3) - without this gate the feed would just be
                        // flooded with ordinary crowd-crowd trades, not highlights.
                        } else if e.action == "TRADE" && e.success && (e.tier == "lead" || e.tier == "player") {
                            if let Some(target_id) = &e.target {
                                let own_society = society_of(sim, &e.agent_id);
                                let target_society = society_of(sim, target_id);
                                if let (Some(own), Some(other)) = (own_society, target_society) {
                                    if own.id != other.id {
                                        let pair = if e.agent_id <= *target_id {
                                            (e.agent_id.clone(), target_id.clone())
                                        } else {
                                            (target_id.clone(), e.agent_id.clone())
                                        };
                                        let on_cooldown = sim.cross_trade_cooldowns.get(&pair)
                                            .map(|&last| e.tick - last < CROSS_TRADE_HIGHLIGHT_COOLDOWN)
                                            .unwrap_or(false);
                                        if !on_cooldown {
                                            let target_name = sim.agents.iter().find(|a| &a.id == target_id)
                                                .and_then(|a| a.display_name.clone()).unwrap_or_else(|| target_id.clone());
                                            sim.highlights.push_back(serde_json::json!({
                                                "tick": e.tick, "kind": "cross_trade", "agent_id": e.agent_id, "display_name": name,
                                                "society": own.id, "target": target_id, "target_display_name": target_name,
                                                "target_society": other.id,
                                            }));
                                            sim.cross_trade_cooldowns.insert(pair, e.tick);
                                        }
                                    }
                                }
                            }
                        }
                    }
                    while sim.notable_events.len() > EVENTS_FEED_CAP {
                        sim.notable_events.pop_front();
                    }
                    while sim.highlights.len() > HIGHLIGHTS_FEED_CAP {
                        sim.highlights.pop_front();
                    }

                    let full_log = sim.full_log;
                    let keep = |e: &seam_core::log::TickLogEntry| full_log || e.tier == "lead" || e.action == "DEATH";

                    if sim.log_writer.is_some() {
                        // Ground-truth society tagging, not inferred after the
                        // fact - the location-clustering heuristic analysis
                        // scripts need otherwise needed two real bug fixes
                        // this session to get right. Built before the mutable
                        // borrow below so society_of's shared borrow of sim
                        // doesn't overlap with it.
                        let enriched: Vec<serde_json::Value> = entries.iter().filter(|e| keep(e)).map(|e| {
                            let mut v = serde_json::to_value(e).expect("log entry must serialize");
                            v["society"] = serde_json::json!(society_of(sim, &e.agent_id).map(|s| s.id.clone()));
                            // Same absent-when-not-applicable rule as main.rs's
                            // batch run path - null for DEATH entries and
                            // LLM-overridden lead ticks, present for everything
                            // choose_action_with_debug actually scored.
                            if let Some(d) = decision_debug.get(&e.agent_id) {
                                v["decision_debug"] = serde_json::to_value(d).expect("decision debug must serialize");
                            }
                            v
                        }).collect();
                        if let Some(writer) = sim.log_writer.as_mut() {
                            for v in &enriched {
                                writer.write(v);
                            }
                        }
                    }

                    if state.pg.is_some() {
                        for e in entries.iter().filter(|e| keep(e)) {
                            let specialty = sim.agents.iter().find(|a| a.id == e.agent_id).map(|a| a.specialty.as_str().to_string());
                            pg_events.push(PgEventRow {
                                tick: e.tick,
                                agent_id: e.agent_id.clone(),
                                tier: e.tier.clone(),
                                specialty,
                                action: e.action.clone(),
                                target: e.target.clone(),
                                success: e.success,
                                state_before: e.state_before.clone(),
                                state_after: e.state_after.clone(),
                                delta: e.delta.clone(),
                            });
                        }
                    }

                    let due_for_periodic = sim.last_stats_write.elapsed().as_secs() >= sim.stats_every_secs;
                    if due_for_periodic {
                        sim.stats.snapshot(tick, &sim.agents, &sim.world, false);
                        sim.last_stats_write = std::time::Instant::now();

                        if state.pg.is_some() {
                            for lead in sim.agents.iter().filter(|a| a.tier == "lead") {
                                pg_lead_memory.push(PgLeadMemRow {
                                    lead_id: lead.id.clone(),
                                    memory_summary: lead.memory_summary.clone(),
                                    caution_bias: lead.caution_bias,
                                    trade_success_ratio: lead.trade_success_ratio(),
                                    hunger_scares_witnessed: lead.hunger_scares_witnessed as i32,
                                });
                            }
                            for society in &sim.societies {
                                let sv = build_society_view(sim, society);
                                pg_settlements.push(PgSettlementRow {
                                    node: sv["node"].as_str().unwrap_or("").to_string(),
                                    population_alive: sv["population_alive"].as_i64().unwrap_or(0) as i32,
                                    roster_size: sv["roster_size"].as_i64().unwrap_or(0) as i32,
                                    avg_energy: sv["avg_energy"].as_f64().unwrap_or(0.0),
                                    avg_hunger: sv["avg_hunger"].as_f64().unwrap_or(0.0),
                                    total_food_held: sv["total_food_held"].as_f64().unwrap_or(0.0),
                                });
                            }
                        }

                        if sim.society_stats_csv.is_some() {
                            let ts = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_secs();
                            let rows: Vec<String> = sim.societies.iter().map(|society| {
                                let sv = build_society_view(sim, society);
                                format!(
                                    "{},{},{},{},{},{},{},{},{}",
                                    tick, ts, sv["id"].as_str().unwrap_or(""), sv["node"].as_str().unwrap_or(""),
                                    sv["population_alive"].as_i64().unwrap_or(0), sv["roster_size"].as_i64().unwrap_or(0),
                                    sv["avg_energy"].as_f64().unwrap_or(0.0), sv["avg_hunger"].as_f64().unwrap_or(0.0),
                                    sv["total_food_held"].as_f64().unwrap_or(0.0),
                                )
                            }).collect();
                            if let Some(f) = sim.society_stats_csv.as_mut() {
                                for row in rows {
                                    writeln!(f, "{row}").expect("write society stats csv row");
                                }
                            }
                        }
                    }

                    build_snapshot(sim, state.started_at)
                };
                let _ = state.tx.send(snap.clone());

                if let Some(pg) = &state.pg {
                    persist_tick(pg, &state.run_id, snap.tick, pg_events, pg_lead_memory, pg_settlements).await;
                }

                tokio::time::sleep(Duration::from_millis(tick_ms)).await;
            }
        });
    }

    let app = Router::new()
        .route("/", get(index_page))
        .route("/state", get(get_state))
        .route("/world", get(get_world))
        .route("/ws", get(ws_handler))
        .route("/agents", get(get_agents))
        .route("/leads", get(get_leads))
        .route("/leads/:id/candidates", get(get_lead_candidates))
        .route("/leads/:id/intent", post(post_lead_intent))
        .route("/leads/:id/memory", post(post_lead_memory))
        .route("/agents/identities", post(post_agent_identities))
        .route("/societies", get(get_societies))
        .route("/player/candidates", get(get_player_candidates))
        .route("/player/action", post(post_player_action))
        .route("/player/possess/:society_id", post(post_player_possess))
        .route("/narrative", get(get_narrative).post(post_narrative))
        .with_state(state);

    let addr = format!("0.0.0.0:{}", a.port);
    println!("seam service listening on http://{addr} (agents={} nodes={} seed={} tick_ms={} societies={})", a.agents, a.nodes, a.seed, a.tick_ms, a.societies);
    let listener = tokio::net::TcpListener::bind(&addr).await.expect("cannot bind port");
    axum::serve(listener, app).await.expect("server error");
}

async fn get_state(State(state): State<Arc<AppState>>) -> Json<Snapshot> {
    let sim = state.sim.lock().unwrap();
    Json(build_snapshot(&sim, state.started_at))
}

/// Viewer pass: the graph's topology - deliberately excludes quantity/
/// signals (which change every tick) so the viewer only ever needs to
/// fetch this once at page load, not poll it, same reasoning /agents is
/// fetched on its own slower cadence rather than folded into the tick
/// stream. Edges are deduped by only including them from their "a" side's
/// adjacency list - add_edge stores the same Edge{a,b,cost} under both
/// endpoints, so filtering to where the current node equals edge.a is
/// enough to avoid emitting each edge twice.
async fn get_world(State(state): State<Arc<AppState>>) -> Json<serde_json::Value> {
    let sim = state.sim.lock().unwrap();
    let nodes: Vec<serde_json::Value> = sim.world.node_order.iter().map(|id| {
        let node = &sim.world.nodes[id];
        serde_json::json!({
            "id": node.id,
            "resource_type": node.resource_type.map(|r| r.as_str()),
        })
    }).collect();
    let mut edges: Vec<serde_json::Value> = Vec::new();
    for node_id in &sim.world.node_order {
        for edge in sim.world.neighbors(node_id) {
            if &edge.a == node_id {
                edges.push(serde_json::json!({ "a": edge.a, "b": edge.b }));
            }
        }
    }
    Json(serde_json::json!({ "nodes": nodes, "edges": edges }))
}

/// Read from disk on every request rather than baked in at compile time -
/// so the viewer can be edited and reloaded in a browser tab without
/// restarting the (possibly hours-old, accumulating) simulation underneath
/// it. Falls back to the embedded copy if the file's missing (e.g. running
/// the binary from somewhere other than core-rs/).
async fn index_page() -> Html<String> {
    const FALLBACK: &str = include_str!("../viewer/index.html");
    let html = std::fs::read_to_string("viewer/index.html").unwrap_or_else(|_| FALLBACK.to_string());
    Html(html)
}

async fn ws_handler(ws: WebSocketUpgrade, State(state): State<Arc<AppState>>) -> impl IntoResponse {
    ws.on_upgrade(move |socket| handle_socket(socket, state))
}

async fn handle_socket(mut socket: WebSocket, state: Arc<AppState>) {
    let initial = {
        let sim = state.sim.lock().unwrap();
        build_snapshot(&sim, state.started_at)
    };
    if socket.send(Message::Text(serde_json::to_string(&initial).unwrap())).await.is_err() {
        return;
    }

    let mut rx = state.tx.subscribe();
    loop {
        tokio::select! {
            msg = rx.recv() => {
                match msg {
                    Ok(snap) => {
                        let payload = serde_json::to_string(&snap).unwrap();
                        if socket.send(Message::Text(payload)).await.is_err() {
                            break;
                        }
                    }
                    Err(broadcast::error::RecvError::Lagged(_)) => continue,
                    Err(broadcast::error::RecvError::Closed) => break,
                }
            }
            incoming = socket.recv() => {
                if incoming.is_none() {
                    break;
                }
            }
        }
    }
}

fn compute_node_occupancy(agents: &[AgentState]) -> HashMap<String, i32> {
    let mut occ: HashMap<String, i32> = HashMap::new();
    for a in agents {
        if a.alive {
            *occ.entry(a.location.clone()).or_insert(0) += 1;
        }
    }
    occ
}

/// Mirrors v1's `leads.py::_describe_candidate` - a short human-readable line
/// for the numbered list the sidecar turns into an LLM prompt.
fn describe_intent(intent: &Intent) -> String {
    let mut parts = vec![intent.action.clone()];
    if let Some(t) = &intent.target {
        parts.push(format!("-> {t}"));
    }
    if intent.action == "TRADE" {
        parts.push(format!(
            "(give {:.0} {}, get {:.0} {})",
            intent.give_amt,
            intent.give.as_deref().unwrap_or(""),
            intent.want_amt,
            intent.want.as_deref().unwrap_or("")
        ));
    }
    if intent.action == "SIGNAL" {
        parts.push(format!("({})", intent.resource.as_deref().unwrap_or("")));
    }
    parts.join(" ")
}

/// Full roster (crowd + leads) - id/tier/display_name only, so the sidecar
/// can find who still needs a name without pulling everyone's full state.
async fn get_agents(State(state): State<Arc<AppState>>) -> Json<Vec<serde_json::Value>> {
    let sim = state.sim.lock().unwrap();
    let out: Vec<serde_json::Value> = sim
        .agents
        .iter()
        .map(|a| serde_json::json!({
            "id": a.id, "tier": a.tier, "display_name": a.display_name,
            "specialty": a.specialty.as_str(), "alive": a.alive,
        }))
        .collect();
    Json(out)
}

async fn get_leads(State(state): State<Arc<AppState>>) -> Json<Vec<serde_json::Value>> {
    let sim = state.sim.lock().unwrap();
    let leads: Vec<serde_json::Value> = sim.agents.iter().filter(|a| a.tier == "lead").map(|a| a.public_view()).collect();
    Json(leads)
}

/// Every legal option for a lead right now, numbered for an LLM prompt.
/// Includes the full Intent, not just an index - the sidecar echoes the
/// whole object back in POST /leads/:id/intent, so a few ticks passing
/// between this GET and that POST (an Ollama call takes real time) can
/// never desync an index against a candidate list that's moved on; the
/// normal resolve-time feasibility recheck (same one v1 relies on) handles
/// anything that's gone stale by the time it's actually applied.
async fn get_lead_candidates(
    Path(id): Path<String>,
    State(state): State<Arc<AppState>>,
) -> Result<Json<Vec<serde_json::Value>>, StatusCode> {
    let sim = state.sim.lock().unwrap();
    let lead = sim.agents.iter().find(|a| a.id == id && a.tier == "lead").ok_or(StatusCode::NOT_FOUND)?;
    let colocated: Vec<&AgentState> = sim.agents.iter().filter(|a| a.alive && a.location == lead.location).collect();
    let node_occupancy = compute_node_occupancy(&sim.agents);
    let candidates = generate_candidates(lead, &sim.world, &colocated, sim.tick, &node_occupancy, sim.trade_enabled);

    let out: Vec<serde_json::Value> = candidates
        .iter()
        .enumerate()
        .map(|(i, (score, intent))| {
            serde_json::json!({
                "index": i + 1,
                "description": describe_intent(intent),
                "score": score,
                "intent": intent,
            })
        })
        .collect();
    Ok(Json(out))
}

async fn post_lead_intent(Path(id): Path<String>, State(state): State<Arc<AppState>>, Json(intent): Json<Intent>) -> StatusCode {
    let mut sim = state.sim.lock().unwrap();
    if !sim.agents.iter().any(|a| a.id == id && a.tier == "lead") {
        return StatusCode::NOT_FOUND;
    }
    sim.pending_intents.insert(id, intent);
    StatusCode::OK
}

/// v3 Phase 0: replaces GET /settlement - one entry per society instead of
/// a single object. Each entry includes its own hatch's state (see
/// build_society_view), so there's no separate per-society hatch endpoint.
async fn get_societies(State(state): State<Arc<AppState>>) -> Json<Vec<serde_json::Value>> {
    let sim = state.sim.lock().unwrap();
    Json(sim.societies.iter().map(|s| build_society_view(&sim, s)).collect())
}

/// v3 Phase 1: resolves whichever society is currently possessed to its
/// hatch id - the one thing that changed about /player/candidates and
/// /player/action, everything else about them is unchanged from Phase 0.
fn possessed_hatch_id(sim: &SimState) -> Option<String> {
    sim.societies.iter().find(|s| s.id == sim.possessed_society).map(|s| s.hatch_id.clone())
}

/// v3 Phase 4: resolves an arbitrary agent id to its society - no existing
/// lookup does this (possessed_hatch_id above only resolves the currently
/// possessed one). Needed to tell a cross-society trade/death apart from
/// an ordinary one.
fn society_of<'a>(sim: &'a SimState, agent_id: &str) -> Option<&'a Society> {
    sim.societies.iter().find(|s| {
        s.roster.iter().any(|id| id == agent_id)
            || s.hatch_id == agent_id
            || s.lead_id.as_deref() == Some(agent_id)
    })
}

/// Same shape as GET /leads/:id/candidates, fixed to whichever society is
/// currently possessed (see possessed_hatch_id) rather than one hardcoded
/// hatch - POST /player/possess/:society_id is what changes that.
async fn get_player_candidates(State(state): State<Arc<AppState>>) -> Result<Json<Vec<serde_json::Value>>, StatusCode> {
    let sim = state.sim.lock().unwrap();
    let hatch_id = possessed_hatch_id(&sim).ok_or(StatusCode::NOT_FOUND)?;
    let hatch = sim.agents.iter().find(|a| a.id == hatch_id).ok_or(StatusCode::NOT_FOUND)?;
    let colocated: Vec<&AgentState> = sim.agents.iter().filter(|a| a.alive && a.location == hatch.location).collect();
    let node_occupancy = compute_node_occupancy(&sim.agents);
    let candidates = generate_candidates(hatch, &sim.world, &colocated, sim.tick, &node_occupancy, sim.trade_enabled);

    let out: Vec<serde_json::Value> = candidates
        .iter()
        .enumerate()
        .map(|(i, (score, intent))| {
            serde_json::json!({
                "index": i + 1,
                "description": describe_intent(intent),
                "score": score,
                "intent": intent,
            })
        })
        .collect();
    Ok(Json(out))
}

/// The hatch's action, submitted straight from the viewer - no LLM in this
/// path at all, this is direct possession. Same pending_intents mechanism
/// leads use: applied for exactly the next tick the hatch is processed.
/// Applies to whichever society is currently possessed, not a fixed hatch.
async fn post_player_action(State(state): State<Arc<AppState>>, Json(intent): Json<Intent>) -> StatusCode {
    let mut sim = state.sim.lock().unwrap();
    let hatch_id = match possessed_hatch_id(&sim) {
        Some(id) => id,
        None => return StatusCode::NOT_FOUND,
    };
    sim.pending_intents.insert(hatch_id, intent);
    StatusCode::OK
}

/// v3 Phase 1: switches which society's hatch /player/action and
/// /player/candidates control. Clears any stale pending_intents entry for
/// the *previous* possessed hatch first - without this, an action queued
/// right before a switch would still apply to the old hatch one tick later,
/// making "unpossessed hatches fall back to autopilot immediately" look
/// like it has a one-tick lag. The old hatch needs no other change to
/// resume autopilot: absence from pending_intents on its next tick is the
/// same fallback guarantee leads already rely on.
async fn post_player_possess(Path(society_id): Path<String>, State(state): State<Arc<AppState>>) -> StatusCode {
    let mut sim = state.sim.lock().unwrap();
    if !sim.societies.iter().any(|s| s.id == society_id) {
        return StatusCode::NOT_FOUND;
    }
    if let Some(previous_hatch_id) = possessed_hatch_id(&sim) {
        sim.pending_intents.remove(&previous_hatch_id);
    }
    sim.possessed_society = society_id;
    StatusCode::OK
}

async fn get_narrative(State(state): State<Arc<AppState>>) -> Json<Vec<serde_json::Value>> {
    let sim = state.sim.lock().unwrap();
    Json(sim.narrative_feed.iter().cloned().collect())
}

#[derive(Deserialize)]
struct NarrativeUpdate {
    text: String,
}

/// The sidecar's periodic scene, appended to a capped rolling feed. Purely
/// additive from the sim's perspective - nothing here can affect the
/// simulation itself, this is read-only narration layered on top.
async fn post_narrative(State(state): State<Arc<AppState>>, Json(update): Json<NarrativeUpdate>) -> StatusCode {
    let (tick, ts) = {
        let mut sim = state.sim.lock().unwrap();
        let tick = sim.tick;
        let ts = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_secs();
        let entry = serde_json::json!({ "tick": tick, "text": update.text, "ts": ts });
        sim.narrative_feed.push_back(entry);
        while sim.narrative_feed.len() > NARRATIVE_FEED_CAP {
            sim.narrative_feed.pop_front();
        }
        (tick, ts as i64)
    };

    if let Some(pg) = &state.pg {
        let _ = pg.execute(
            "INSERT INTO narrative_scenes (run_id, tick, text, ts) VALUES ($1, $2, $3, $4)",
            &[&state.run_id, &tick, &update.text, &ts],
        ).await;
    }

    StatusCode::OK
}

#[derive(Deserialize)]
struct MemoryUpdate {
    // caution_bias is deliberately not settable here - it's derived
    // mechanically every tick from the trade/hunger counters (see
    // AgentState::recompute_caution_bias). This endpoint is for the
    // LLM-authored narrative text only.
    memory_summary: Option<String>,
}

async fn post_lead_memory(Path(id): Path<String>, State(state): State<Arc<AppState>>, Json(update): Json<MemoryUpdate>) -> StatusCode {
    let mut sim = state.sim.lock().unwrap();
    let lead = match sim.agents.iter_mut().find(|a| a.id == id && a.tier == "lead") {
        Some(l) => l,
        None => return StatusCode::NOT_FOUND,
    };
    if let Some(summary) = update.memory_summary {
        lead.memory_summary = summary;
    }
    StatusCode::OK
}

#[derive(Deserialize)]
struct IdentityUpdate {
    id: String,
    display_name: Option<String>,
    blurb: Option<String>,
}

async fn post_agent_identities(State(state): State<Arc<AppState>>, Json(updates): Json<Vec<IdentityUpdate>>) -> StatusCode {
    let mut sim = state.sim.lock().unwrap();
    let mut by_id: HashMap<String, &mut AgentState> = HashMap::new();
    for a in sim.agents.iter_mut() {
        by_id.insert(a.id.clone(), a);
    }
    for update in updates {
        if let Some(agent) = by_id.get_mut(&update.id) {
            if update.display_name.is_some() {
                agent.display_name = update.display_name;
            }
            if update.blurb.is_some() {
                agent.blurb = update.blurb;
            }
        }
    }
    StatusCode::OK
}
