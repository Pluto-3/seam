//! Phase 1: the persistent simulation service. The world ticks continuously
//! in a background task, independent of whether anyone is watching. Viewers
//! connect over WebSocket for a live push feed, or hit /state once over
//! REST, and can disconnect/reconnect without affecting the sim underneath.

use std::collections::HashMap;
use std::env;
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

use seam_core::agents::{spawn_leads, AgentState};
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
    hatch: Option<serde_json::Value>,
    settlement: serde_json::Value,
}

const HATCH_ID: &str = "hatch0";
const SETTLEMENT_ROSTER_SIZE: usize = 8;

struct SimState {
    world: World,
    agents: Vec<AgentState>,
    rng: ChaCha8Rng,
    tick: i64,
    stats: StatsTracker,
    trade_enabled: bool,
    // Phase 3: one designated node + a fixed roster of crowd agents who live
    // there - the thing the player is actually responsible for. No new
    // mechanic, just a label on an existing node and a fixed list of ids.
    settlement_node: String,
    settlement_roster: Vec<String>,
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
    stats_every_secs: u64,
    last_stats_write: std::time::Instant,
}

struct AppState {
    sim: Mutex<SimState>,
    tx: broadcast::Sender<Snapshot>,
    started_at: std::time::Instant,
}

/// Raw numbers only, deliberately no composite score - population, average
/// hunger/energy of the settlement's own roster, and how much food they
/// collectively have on hand right now. Nothing invented or weighted.
fn build_settlement_view(sim: &SimState) -> serde_json::Value {
    let roster: Vec<&AgentState> = sim.agents.iter().filter(|a| sim.settlement_roster.contains(&a.id)).collect();
    let alive: Vec<&&AgentState> = roster.iter().filter(|a| a.alive).collect();
    let population_alive = alive.len();
    let roster_size = roster.len();
    let avg_energy = if population_alive > 0 { alive.iter().map(|a| a.energy).sum::<f64>() / population_alive as f64 } else { 0.0 };
    let avg_hunger = if population_alive > 0 { alive.iter().map(|a| a.hunger).sum::<f64>() / population_alive as f64 } else { 0.0 };
    let total_food_held: f64 = alive.iter().map(|a| a.held(ResourceType::Food)).sum();
    serde_json::json!({
        "node": sim.settlement_node,
        "roster_size": roster_size,
        "population_alive": population_alive,
        "avg_energy": avg_energy,
        "avg_hunger": avg_hunger,
        "total_food_held": total_food_held,
    })
}

fn build_snapshot(sim: &SimState, started_at: std::time::Instant) -> Snapshot {
    let alive: Vec<&AgentState> = sim.agents.iter().filter(|a| a.alive).collect();
    let population = alive.len();
    let total = sim.agents.len();
    let avg_energy = if population > 0 { alive.iter().map(|a| a.energy).sum::<f64>() / population as f64 } else { 0.0 };
    let avg_hunger = if population > 0 { alive.iter().map(|a| a.hunger).sum::<f64>() / population as f64 } else { 0.0 };
    let leads: Vec<serde_json::Value> = sim.agents.iter().filter(|a| a.tier == "lead").map(|a| a.public_view()).collect();
    let hatch = sim.agents.iter().find(|a| a.id == HATCH_ID).map(|a| a.public_view());
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
        hatch,
        settlement: build_settlement_view(sim),
    }
}

#[tokio::main]
async fn main() {
    let a = parse_args();

    let mut rng = ChaCha8Rng::seed_from_u64(a.seed);
    let world = generate_world(a.nodes, &mut rng);
    let mut agents = seam_core::agents::spawn_agents(a.agents, &world, &mut rng);
    agents.extend(spawn_leads(&world, &mut rng));

    // Phase 3: designate a settlement - one node, plus a fixed roster of
    // crowd agents relocated there so it's guaranteed to actually have
    // inhabitants (spawn_agents scatters them randomly; leaving this to
    // chance could hand the player an empty settlement on an unlucky seed).
    let settlement_node = world.node_order[0].clone();
    let mut settlement_roster: Vec<String> = Vec::new();
    for agent in agents.iter_mut().filter(|a| a.tier == "crowd").take(SETTLEMENT_ROSTER_SIZE) {
        agent.location = settlement_node.clone();
        settlement_roster.push(agent.id.clone());
    }

    // The hatch - one player-controlled agent, spawned at the settlement.
    // Starting stats deliberately fixed, not randomized: it's a single
    // special agent, not part of spawn_agents' statistical distribution.
    let hatch_specialty = seam_core::world::RAW_RESOURCES[0];
    agents.push(AgentState::new_player(HATCH_ID.to_string(), settlement_node.clone(), 80.0, 20.0, hatch_specialty));

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

    let sim = SimState {
        world,
        agents,
        rng,
        tick: 0,
        stats: StatsTracker::new(a.stats_csv.as_deref()),
        trade_enabled: !a.no_trade,
        settlement_node,
        settlement_roster,
        pending_intents: HashMap::new(),
        log_writer: a.log_path.as_deref().map(JsonlWriter::new),
        full_log: a.full_log,
        stats_every_secs: a.stats_every_secs,
        last_stats_write: std::time::Instant::now(),
    };

    let (tx, _rx) = broadcast::channel(32);
    let state = Arc::new(AppState { sim: Mutex::new(sim), tx: tx.clone(), started_at: std::time::Instant::now() });

    {
        let state = state.clone();
        let tick_ms = a.tick_ms;
        tokio::spawn(async move {
            loop {
                let snap = {
                    let mut guard = state.sim.lock().unwrap();
                    let sim: &mut SimState = &mut guard;
                    sim.tick += 1;
                    let trade_enabled = sim.trade_enabled;
                    let tick = sim.tick;
                    let due_intents = std::mem::take(&mut sim.pending_intents);
                    let entries = run_tick(tick, &mut sim.world, &mut sim.agents, &mut sim.rng, trade_enabled, &due_intents, true);
                    sim.stats.consume(&entries);

                    if let Some(writer) = sim.log_writer.as_mut() {
                        let full_log = sim.full_log;
                        for e in &entries {
                            if full_log || e.tier == "lead" || e.action == "DEATH" {
                                writer.write(e);
                            }
                        }
                    }
                    if sim.last_stats_write.elapsed().as_secs() >= sim.stats_every_secs {
                        sim.stats.snapshot(tick, &sim.agents, &sim.world, false);
                        sim.last_stats_write = std::time::Instant::now();
                    }

                    build_snapshot(sim, state.started_at)
                };
                let _ = state.tx.send(snap);
                tokio::time::sleep(Duration::from_millis(tick_ms)).await;
            }
        });
    }

    let app = Router::new()
        .route("/", get(index_page))
        .route("/state", get(get_state))
        .route("/ws", get(ws_handler))
        .route("/agents", get(get_agents))
        .route("/leads", get(get_leads))
        .route("/leads/:id/candidates", get(get_lead_candidates))
        .route("/leads/:id/intent", post(post_lead_intent))
        .route("/leads/:id/memory", post(post_lead_memory))
        .route("/agents/identities", post(post_agent_identities))
        .route("/settlement", get(get_settlement))
        .route("/player/candidates", get(get_player_candidates))
        .route("/player/action", post(post_player_action))
        .with_state(state);

    let addr = format!("0.0.0.0:{}", a.port);
    println!("seam service listening on http://{addr} (agents={} nodes={} seed={} tick_ms={})", a.agents, a.nodes, a.seed, a.tick_ms);
    let listener = tokio::net::TcpListener::bind(&addr).await.expect("cannot bind port");
    axum::serve(listener, app).await.expect("server error");
}

async fn get_state(State(state): State<Arc<AppState>>) -> Json<Snapshot> {
    let sim = state.sim.lock().unwrap();
    Json(build_snapshot(&sim, state.started_at))
}

async fn index_page() -> Html<&'static str> {
    Html(include_str!("../viewer/index.html"))
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
        .map(|a| serde_json::json!({"id": a.id, "tier": a.tier, "display_name": a.display_name}))
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

async fn get_settlement(State(state): State<Arc<AppState>>) -> Json<serde_json::Value> {
    let sim = state.sim.lock().unwrap();
    Json(build_settlement_view(&sim))
}

/// Same shape as GET /leads/:id/candidates, just fixed to the one hatch
/// agent rather than taking a path id - there's only ever one hatch.
async fn get_player_candidates(State(state): State<Arc<AppState>>) -> Result<Json<Vec<serde_json::Value>>, StatusCode> {
    let sim = state.sim.lock().unwrap();
    let hatch = sim.agents.iter().find(|a| a.id == HATCH_ID).ok_or(StatusCode::NOT_FOUND)?;
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
async fn post_player_action(State(state): State<Arc<AppState>>, Json(intent): Json<Intent>) -> StatusCode {
    let mut sim = state.sim.lock().unwrap();
    if !sim.agents.iter().any(|a| a.id == HATCH_ID) {
        return StatusCode::NOT_FOUND;
    }
    sim.pending_intents.insert(HATCH_ID.to_string(), intent);
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
