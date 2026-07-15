//! Phase 1: the persistent simulation service. The world ticks continuously
//! in a background task, independent of whether anyone is watching. Viewers
//! connect over WebSocket for a live push feed, or hit /state once over
//! REST, and can disconnect/reconnect without affecting the sim underneath.

use std::env;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use axum::extract::ws::{Message, WebSocket, WebSocketUpgrade};
use axum::extract::State;
use axum::response::{Html, IntoResponse};
use axum::routing::get;
use axum::{Json, Router};
use rand::SeedableRng;
use rand_chacha::ChaCha8Rng;
use serde::Serialize;
use tokio::sync::broadcast;

use seam_core::agents::AgentState;
use seam_core::stats::StatsTracker;
use seam_core::tick::run_tick;
use seam_core::world::{generate_world, World};

struct Args {
    agents: usize,
    nodes: usize,
    seed: u64,
    tick_ms: u64,
    port: u16,
    no_trade: bool,
}

fn parse_args() -> Args {
    let mut a = Args { agents: 40, nodes: 15, seed: 42, tick_ms: 200, port: 7878, no_trade: false };
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
}

struct SimState {
    world: World,
    agents: Vec<AgentState>,
    rng: ChaCha8Rng,
    tick: i64,
    stats: StatsTracker,
    trade_enabled: bool,
}

struct AppState {
    sim: Mutex<SimState>,
    tx: broadcast::Sender<Snapshot>,
    started_at: std::time::Instant,
}

fn build_snapshot(sim: &SimState, started_at: std::time::Instant) -> Snapshot {
    let alive: Vec<&AgentState> = sim.agents.iter().filter(|a| a.alive).collect();
    let population = alive.len();
    let total = sim.agents.len();
    let avg_energy = if population > 0 { alive.iter().map(|a| a.energy).sum::<f64>() / population as f64 } else { 0.0 };
    let avg_hunger = if population > 0 { alive.iter().map(|a| a.hunger).sum::<f64>() / population as f64 } else { 0.0 };
    Snapshot {
        tick: sim.tick,
        population,
        total,
        avg_energy,
        avg_hunger,
        specialization_index: sim.stats.specialization_index(&sim.agents),
        trades_cumulative: sim.stats.cumulative_trades(),
        uptime_secs: started_at.elapsed().as_secs(),
    }
}

#[tokio::main]
async fn main() {
    let a = parse_args();

    let mut rng = ChaCha8Rng::seed_from_u64(a.seed);
    let world = generate_world(a.nodes, &mut rng);
    let agents = seam_core::agents::spawn_agents(a.agents, &world, &mut rng);
    let sim = SimState { world, agents, rng, tick: 0, stats: StatsTracker::new(None), trade_enabled: !a.no_trade };

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
                    let entries = run_tick(tick, &mut sim.world, &mut sim.agents, &mut sim.rng, trade_enabled);
                    sim.stats.consume(&entries);
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
