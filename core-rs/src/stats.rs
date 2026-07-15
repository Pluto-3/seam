//! Rolling + cumulative stats over the tick log, printed periodically.
//! Ported from `stats.py`. `specialization_index` is the key derived number:
//! the average fraction of an agent's held raw inventory that is *not* their
//! own specialty. Trending upward over a run is the clearest evidence that
//! trade is redistributing goods by need, not noise.

use std::collections::HashMap;
use std::fs::File;
use std::io::Write;

use crate::agents::AgentState;
use crate::log::TickLogEntry;
use crate::world::{ResourceType, World, RAW_RESOURCES};

pub struct StatsTracker {
    trade_leg_count: u64,
    trade_leg_volume: f64,
    pub cumulative_crafts: u64,

    window_trade_leg_count: u64,
    window_trade_leg_volume: f64,
    window_crafts: u64,
    window_routes: HashMap<(String, String), u64>,
    window_gathers: HashMap<(String, String), u64>,

    csv_file: Option<File>,
}

impl StatsTracker {
    pub fn new(csv_path: Option<&str>) -> Self {
        let csv_file = csv_path.map(|p| {
            let mut f = File::create(p).expect("cannot create stats csv");
            writeln!(
                f,
                "tick,population,avg_energy,avg_hunger,avg_ore,avg_food,avg_wood,trades_window,trades_cum,trade_volume_window,trade_volume_cum,crafts_window,crafts_cum,signals_active,specialization_index"
            )
            .unwrap();
            f
        });
        StatsTracker {
            trade_leg_count: 0,
            trade_leg_volume: 0.0,
            cumulative_crafts: 0,
            window_trade_leg_count: 0,
            window_trade_leg_volume: 0.0,
            window_crafts: 0,
            window_routes: HashMap::new(),
            window_gathers: HashMap::new(),
            csv_file,
        }
    }

    pub fn consume(&mut self, entries: &[TickLogEntry]) {
        for e in entries {
            if e.action == "TRADE" && e.success {
                self.trade_leg_count += 1;
                self.window_trade_leg_count += 1;
                let vol: f64 = e
                    .delta
                    .as_object()
                    .map(|m| {
                        m.iter()
                            .filter(|(k, _)| k.starts_with("inventory."))
                            .map(|(_, v)| v.as_f64().unwrap_or(0.0).abs())
                            .sum::<f64>()
                    })
                    .unwrap_or(0.0)
                    / 2.0;
                self.trade_leg_volume += vol;
                self.window_trade_leg_volume += vol;
            } else if e.action == "CRAFT" && e.success {
                self.cumulative_crafts += 1;
                self.window_crafts += 1;
            } else if e.action == "MOVE" && e.success {
                let before_loc = e.state_before["location"].as_str().unwrap_or("").to_string();
                let after_loc = e.state_after["location"].as_str().unwrap_or("").to_string();
                let mut route = [before_loc, after_loc];
                route.sort();
                let key = (route[0].clone(), route[1].clone());
                *self.window_routes.entry(key).or_insert(0) += 1;
            } else if e.action == "GATHER" && e.success {
                let resource = e.delta.as_object().and_then(|m| {
                    m.keys().find(|k| k.starts_with("inventory.")).map(|k| k.rsplit('.').next().unwrap().to_string())
                });
                if let (Some(resource), Some(target)) = (resource, e.target.clone()) {
                    *self.window_gathers.entry((target, resource)).or_insert(0) += 1;
                }
            }
        }
    }

    pub fn cumulative_trades(&self) -> u64 {
        self.trade_leg_count / 2
    }

    pub fn specialization_index(&self, agents: &[AgentState]) -> f64 {
        let alive: Vec<&AgentState> = agents.iter().filter(|a| a.alive).collect();
        let mut fractions = Vec::new();
        for a in &alive {
            let total: f64 = RAW_RESOURCES.iter().map(|&r| a.held(r)).sum();
            if total <= 0.0 {
                continue;
            }
            let non_specialty = total - a.held(a.specialty);
            fractions.push(non_specialty / total);
        }
        if fractions.is_empty() {
            0.0
        } else {
            fractions.iter().sum::<f64>() / fractions.len() as f64
        }
    }

    pub fn signals_active(&self, world: &World) -> usize {
        world.nodes.values().map(|n| n.signals.len()).sum()
    }

    pub fn reset_window(&mut self) {
        self.window_trade_leg_count = 0;
        self.window_trade_leg_volume = 0.0;
        self.window_crafts = 0;
        self.window_routes.clear();
        self.window_gathers.clear();
    }

    pub fn snapshot(&mut self, tick: i64, agents: &[AgentState], world: &World, print_output: bool) {
        let alive: Vec<&AgentState> = agents.iter().filter(|a| a.alive).collect();
        let population = alive.len();
        let total = agents.len();
        let avg_energy = if population > 0 { alive.iter().map(|a| a.energy).sum::<f64>() / population as f64 } else { 0.0 };
        let avg_hunger = if population > 0 { alive.iter().map(|a| a.hunger).sum::<f64>() / population as f64 } else { 0.0 };
        let avg_ore =
            if population > 0 { alive.iter().map(|a| a.held(ResourceType::Ore)).sum::<f64>() / population as f64 } else { 0.0 };
        let avg_food =
            if population > 0 { alive.iter().map(|a| a.held(ResourceType::Food)).sum::<f64>() / population as f64 } else { 0.0 };
        let avg_wood =
            if population > 0 { alive.iter().map(|a| a.held(ResourceType::Wood)).sum::<f64>() / population as f64 } else { 0.0 };
        let signals_active = self.signals_active(world);
        let spec_idx = self.specialization_index(agents);

        let trades_window = self.window_trade_leg_count / 2;
        let trades_cum = self.trade_leg_count / 2;
        let volume_window = self.window_trade_leg_volume / 2.0;
        let volume_cum = self.trade_leg_volume / 2.0;

        if print_output {
            println!("=== tick {tick} ===");
            println!("population        : {population} / {total} alive ({} dead)", total - population);
            println!("avg energy        : {avg_energy:.1}");
            println!("avg hunger        : {avg_hunger:.1}");
            println!("avg inventory     : ore={avg_ore:.2} food={avg_food:.2} wood={avg_wood:.2}");
            println!("trades            : window={trades_window}  cumulative={trades_cum}");
            println!("trade volume      : window={volume_window:.1}  cumulative={volume_cum:.1}");
            println!("crafts            : window={}  cumulative={}", self.window_crafts, self.cumulative_crafts);
            println!("signals active    : {signals_active}");
            println!("specialization idx: {spec_idx:.2}");
            println!();
        }

        if let Some(f) = self.csv_file.as_mut() {
            writeln!(
                f,
                "{tick},{population},{:.2},{:.2},{:.3},{:.3},{:.3},{trades_window},{trades_cum},{:.2},{:.2},{},{},{signals_active},{:.3}",
                avg_energy,
                avg_hunger,
                avg_ore,
                avg_food,
                avg_wood,
                volume_window,
                volume_cum,
                self.window_crafts,
                self.cumulative_crafts,
                spec_idx
            )
            .unwrap();
        }

        self.reset_window();
    }
}
