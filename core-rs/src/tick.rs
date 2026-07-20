//! The tick loop: regen -> metabolism -> decide -> resolve -> log. Ported from `tick.py`.
//!
//! Authoritative resolve order: MOVE, GATHER, CRAFT, CONSUME, TRADE, REST, SIGNAL.
//! Trade resolves after Move so an agent that just walked to a partner can
//! still trade that tick. Rest is the only energy-recovering action, resolved
//! after Trade so Move/Gather's energy costs are real opportunity costs.

use rand::seq::SliceRandom;
use rand::Rng;
use std::collections::HashMap;

use crate::actions as act;
use crate::agents::AgentState;
use crate::constants as C;
use crate::decide::{choose_action_with_debug, DecisionDebug, Intent};
use crate::log::{diff, TickLogEntry};
use crate::world::World;

fn is_dead(agent: &AgentState) -> bool {
    agent.hunger >= C::DEATH_HUNGER_MAX || agent.energy <= C::DEATH_ENERGY_MIN
}

fn death_entry(tick: i64, agent: &mut AgentState) -> TickLogEntry {
    let before = agent.snapshot();
    agent.alive = false;
    let after = agent.snapshot();
    let delta = diff(&before, &after);
    TickLogEntry {
        tick,
        agent_id: agent.id.clone(),
        tier: agent.tier.clone(),
        state_before: before,
        action: "DEATH".to_string(),
        target: None,
        success: true,
        state_after: after,
        delta,
    }
}

pub fn run_tick(
    tick: i64,
    world: &mut World,
    agents: &mut Vec<AgentState>,
    rng: &mut impl Rng,
    trade_enabled: bool,
    external_intents: &HashMap<String, Intent>,
    memory_enabled: bool,
    order_strength: f64,
) -> (Vec<TickLogEntry>, HashMap<String, DecisionDebug>) {
    let mut entries: Vec<TickLogEntry> = Vec::new();

    // 1. housekeeping
    world.regen();
    world.prune_signals(tick);

    // 2. metabolism + death check pass 1 (also: memory bookkeeping for hunger
    // scares - counts entering the emergency zone once per episode, not once
    // per tick spent in it)
    for agent in agents.iter_mut() {
        if !agent.alive {
            continue;
        }
        let was_scared = agent.hunger >= C::HUNGER_EMERGENCY_THRESHOLD;
        agent.hunger = (agent.hunger + C::HUNGER_RATE).min(100.0);
        agent.energy = (agent.energy - C::ENERGY_DECAY_RATE).max(0.0);
        if !was_scared && agent.hunger >= C::HUNGER_EMERGENCY_THRESHOLD {
            agent.hunger_scares_witnessed += 1;
        }
        if is_dead(agent) {
            entries.push(death_entry(tick, agent));
        }
    }

    // 3. decide, from one consistent post-metabolism snapshot
    let mut by_location: HashMap<String, Vec<usize>> = HashMap::new();
    for (idx, agent) in agents.iter().enumerate() {
        if agent.alive {
            by_location.entry(agent.location.clone()).or_default().push(idx);
        }
    }
    let node_occupancy: HashMap<String, i32> = by_location.iter().map(|(k, v)| (k.clone(), v.len() as i32)).collect();

    let mut id_to_idx: HashMap<String, usize> = HashMap::new();
    for (idx, agent) in agents.iter().enumerate() {
        id_to_idx.insert(agent.id.clone(), idx);
    }

    let mut intents: HashMap<String, Intent> = HashMap::new();
    // Populated only when choose_action_with_debug actually ran - an LLM-
    // overridden lead's tick has no candidate scores to report, so it's
    // simply absent from this map rather than faked.
    let mut decision_debug: HashMap<String, DecisionDebug> = HashMap::new();
    for idx in 0..agents.len() {
        if !agents[idx].alive {
            continue;
        }
        let loc = agents[idx].location.clone();
        let colocated_idxs = by_location.get(&loc).cloned().unwrap_or_default();
        let colocated: Vec<&AgentState> = colocated_idxs.iter().map(|&i| &agents[i]).collect();
        // A lead with a fresh decision waiting (from the Python sidecar's LLM
        // call) uses it for exactly this tick; absent, it runs on the same
        // autopilot as the crowd - mirrors v1's external_intents semantics.
        let intent = match external_intents.get(&agents[idx].id) {
            Some(ov) => ov.clone(),
            None => {
                let (intent, debug) =
                    choose_action_with_debug(&agents[idx], world, &colocated, tick, rng, &node_occupancy, trade_enabled, order_strength);
                decision_debug.insert(agents[idx].id.clone(), debug);
                intent
            }
        };
        intents.insert(agents[idx].id.clone(), intent);
    }

    // 4. resolve in fixed phase order, each phase in shuffled agent order
    for phase in ["MOVE", "GATHER", "CRAFT", "CONSUME"] {
        let mut actors: Vec<usize> = (0..agents.len())
            .filter(|&i| agents[i].alive && intents.get(&agents[i].id).map(|it| it.action == phase).unwrap_or(false))
            .collect();
        actors.shuffle(rng);
        for i in actors {
            let intent = intents.get(&agents[i].id).unwrap().clone();
            let e = match phase {
                "MOVE" => act::resolve_move(&mut agents[i], world, &intent, tick),
                "GATHER" => act::resolve_gather(&mut agents[i], world, &intent, tick),
                "CRAFT" => act::resolve_craft(&mut agents[i], &intent, tick),
                "CONSUME" => act::resolve_consume(&mut agents[i], &intent, tick),
                _ => unreachable!(),
            };
            entries.push(e);
        }
    }

    let trade_entries = act::resolve_trade_phase(agents, &id_to_idx, &intents, tick, rng);
    // Memory bookkeeping: every agent that attempted a trade this tick records
    // whether it actually resolved - this is what a lead's periodic
    // self-summary reads to decide whether it's had "a bad run of trades."
    for e in &trade_entries {
        if let Some(&idx) = id_to_idx.get(&e.agent_id) {
            agents[idx].record_trade_outcome(e.success);
        }
    }
    entries.extend(trade_entries);

    for phase in ["REST", "SIGNAL"] {
        let mut actors: Vec<usize> = (0..agents.len())
            .filter(|&i| agents[i].alive && intents.get(&agents[i].id).map(|it| it.action == phase).unwrap_or(false))
            .collect();
        actors.shuffle(rng);
        for i in actors {
            let intent = intents.get(&agents[i].id).unwrap().clone();
            let e = match phase {
                "REST" => act::resolve_rest(&mut agents[i], &intent, tick),
                "SIGNAL" => act::resolve_signal(&mut agents[i], world, &intent, tick),
                _ => unreachable!(),
            };
            entries.push(e);
        }
    }

    // 5. death check pass 2 - move/gather energy costs can be the actual tipping point
    for agent in agents.iter_mut() {
        if agent.alive && is_dead(agent) {
            entries.push(death_entry(tick, agent));
        }
    }

    // 6. memory: recompute each lead's mechanical caution_bias from this
    // tick's updated counters (no-op for crowd agents). Gateable purely for
    // the Phase 2 memory-on-vs-off verification experiment - every real
    // caller (serve, run) leaves this true.
    if memory_enabled {
        for agent in agents.iter_mut() {
            agent.recompute_caution_bias();
        }
    }

    (entries, decision_debug)
}
