//! Entry point. Ported from `run.py`.
//!
//!     run --ticks 8000 --agents 40 --nodes 15 --seed 42
//!     run --selftest --seed 0
//!     run --no-trade --seed 42   (negative control)

use rand::SeedableRng;
use rand_chacha::ChaCha8Rng;
use std::collections::HashMap;
use std::env;

use seam_core::agents::{spawn_agents, spawn_leads};
use seam_core::constants::ORDER_GATHER_MULTIPLIER;
use seam_core::log::JsonlWriter;
use seam_core::stats::StatsTracker;
use seam_core::tick::run_tick;
use seam_core::world::generate_world;

struct Args {
    ticks: i64,
    agents: usize,
    nodes: usize,
    seed: u64,
    stats_every: i64,
    log_path: String,
    stats_csv: String,
    no_trade: bool,
    selftest: bool,
    quiet: bool,
    with_leads: bool,
    no_memory: bool,
    order_strength: f64,
}

fn parse_args() -> Args {
    let mut a = Args {
        ticks: 2000,
        agents: 40,
        nodes: 15,
        seed: 0,
        stats_every: 100,
        log_path: "logs/run.jsonl".to_string(),
        stats_csv: "logs/stats.csv".to_string(),
        no_trade: false,
        selftest: false,
        quiet: false,
        with_leads: false,
        no_memory: false,
        order_strength: ORDER_GATHER_MULTIPLIER,
    };
    let argv: Vec<String> = env::args().collect();
    let mut i = 1;
    while i < argv.len() {
        match argv[i].as_str() {
            "--ticks" => {
                a.ticks = argv[i + 1].parse().expect("--ticks must be an integer");
                i += 2;
            }
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
            "--stats-every" => {
                a.stats_every = argv[i + 1].parse().expect("--stats-every must be an integer");
                i += 2;
            }
            "--log-path" => {
                a.log_path = argv[i + 1].clone();
                i += 2;
            }
            "--stats-csv" => {
                a.stats_csv = argv[i + 1].clone();
                i += 2;
            }
            "--no-trade" => {
                a.no_trade = true;
                i += 1;
            }
            "--selftest" => {
                a.selftest = true;
                i += 1;
            }
            "--quiet" => {
                a.quiet = true;
                i += 1;
            }
            "--with-leads" => {
                a.with_leads = true;
                i += 1;
            }
            "--no-memory" => {
                a.no_memory = true;
                i += 1;
            }
            "--order-strength" => {
                a.order_strength = argv[i + 1].parse().expect("--order-strength must be a float");
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

fn ensure_parent_dir(path: &str) {
    if let Some(parent) = std::path::Path::new(path).parent() {
        if !parent.as_os_str().is_empty() {
            std::fs::create_dir_all(parent).expect("cannot create parent directory");
        }
    }
}

fn selftest(a: &Args) -> i32 {
    let mut rng = ChaCha8Rng::seed_from_u64(a.seed);
    let mut world = generate_world(a.nodes, &mut rng);
    let mut ok = true;

    if !world.is_connected() {
        println!("FAIL: generated world is not fully connected");
        ok = false;
    } else {
        println!("OK: world is fully connected");
    }

    let mut agents = spawn_agents(a.agents, &world, &mut rng);
    let trade_enabled = !a.no_trade;
    for t in 1..=50i64 {
        run_tick(t, &mut world, &mut agents, &mut rng, trade_enabled, &HashMap::new(), true, a.order_strength);
        for ag in &agents {
            if !(-1e-6..=100.0 + 1e-6).contains(&ag.energy) {
                println!("FAIL: agent {} energy out of range at tick {t}: {}", ag.id, ag.energy);
                ok = false;
            }
            if !(-1e-6..=100.0 + 1e-6).contains(&ag.hunger) {
                println!("FAIL: agent {} hunger out of range at tick {t}: {}", ag.id, ag.hunger);
                ok = false;
            }
            for (res, amt) in &ag.inventory {
                if *amt < -1e-6 {
                    println!("FAIL: agent {} negative inventory {res}={amt} at tick {t}", ag.id);
                    ok = false;
                }
            }
        }
    }

    if ok {
        println!("OK: 50-tick run stayed within valid state bounds");
    }
    println!("{}", if ok { "SELFTEST PASSED" } else { "SELFTEST FAILED" });
    if ok {
        0
    } else {
        1
    }
}

fn main() {
    let a = parse_args();

    if a.selftest {
        std::process::exit(selftest(&a));
    }

    let mut rng = ChaCha8Rng::seed_from_u64(a.seed);
    let mut world = generate_world(a.nodes, &mut rng);
    let mut agent_list = spawn_agents(a.agents, &world, &mut rng);
    if a.with_leads {
        agent_list.extend(spawn_leads(&world, &mut rng));
    }
    let memory_enabled = !a.no_memory;

    ensure_parent_dir(&a.log_path);
    ensure_parent_dir(&a.stats_csv);

    let mut log_writer = JsonlWriter::new(&a.log_path);
    let mut stats = StatsTracker::new(Some(&a.stats_csv));

    if !a.quiet {
        println!(
            "seam-core (Rust) - agents={} nodes={} ticks={} seed={} trade={} order_strength={}",
            a.agents,
            a.nodes,
            a.ticks,
            a.seed,
            if a.no_trade { "OFF" } else { "on" },
            a.order_strength
        );
        println!();
    }

    let trade_enabled = !a.no_trade;
    for t in 1..=a.ticks {
        let (entries, decision_debug) =
            run_tick(t, &mut world, &mut agent_list, &mut rng, trade_enabled, &HashMap::new(), memory_enabled, a.order_strength);
        // Enrichment, not a TickLogEntry field: decision_debug only exists for
        // agents whose tick actually went through choose_action_with_debug
        // (not DEATH entries, not LLM-overridden lead ticks), so it's attached
        // per-entry here rather than forced into the struct everyone gets.
        for e in &entries {
            match decision_debug.get(&e.agent_id) {
                Some(d) => {
                    let mut v = serde_json::to_value(e).expect("log entry must serialize");
                    v["decision_debug"] = serde_json::to_value(d).expect("decision debug must serialize");
                    log_writer.write(&v);
                }
                None => log_writer.write(e),
            }
        }
        stats.consume(&entries);
        if t % a.stats_every == 0 || t == a.ticks {
            stats.snapshot(t, &agent_list, &world, !a.quiet);
        }
    }

    log_writer.close();
}
