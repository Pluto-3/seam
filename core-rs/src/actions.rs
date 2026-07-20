//! Per-action resolution: mutate world/agent state, produce a TickLogEntry.
//! Ported from `actions.py`. Trade resolves as a single-shot offer/accept: the
//! initiator's candidate was already checked at decide time to be mutually
//! beneficial using the partner's observed inventory; at resolution time we
//! re-check against the partner's *current* state and, if it's still not a
//! loss for the partner, execute the swap immediately.

use rand::seq::SliceRandom;
use rand::Rng;
use std::collections::HashMap;

use crate::agents::AgentState;
use crate::constants as C;
use crate::decide::{marginal_value, Intent};
use crate::log::{diff, TickLogEntry};
use crate::world::{ResourceType, Signal, World};

fn entry(
    tick: i64,
    agent: &AgentState,
    action: &str,
    target: Option<String>,
    success: bool,
    before: serde_json::Value,
    after: serde_json::Value,
) -> TickLogEntry {
    let delta = diff(&before, &after);
    TickLogEntry {
        tick,
        agent_id: agent.id.clone(),
        tier: agent.tier.clone(),
        state_before: before,
        action: action.to_string(),
        target,
        success,
        state_after: after,
        delta,
    }
}

pub fn resolve_move(agent: &mut AgentState, world: &World, intent: &Intent, tick: i64) -> TickLogEntry {
    let before = agent.snapshot();
    let target = intent.target.clone().unwrap();
    let edge = world.neighbors(&agent.location).iter().find(|e| e.other(&agent.location) == target).cloned();
    let success = edge.is_some();
    if let Some(e) = edge {
        agent.location = target.clone();
        agent.energy = (agent.energy - e.cost * C::MOVE_ENERGY_COST_FACTOR).max(0.0);
    }
    let after = agent.snapshot();
    entry(tick, agent, "MOVE", Some(target), success, before, after)
}

pub fn resolve_gather(agent: &mut AgentState, world: &mut World, intent: &Intent, tick: i64) -> TickLogEntry {
    let before = agent.snapshot();
    let resource = ResourceType::from_str(intent.resource.as_ref().unwrap());
    let target = intent.target.clone().unwrap();

    let success = {
        let node = &world.nodes[&agent.location];
        node.id == target && node.resource_type == Some(resource) && node.quantity > 0.0
    };

    if success {
        let mut mult = if resource == agent.specialty { C::SPECIALTY_GATHER_MULTIPLIER } else { C::OFF_SPECIALTY_GATHER_MULTIPLIER };
        if agent.tool_durability > 0 {
            mult *= C::TOOL_GATHER_MULTIPLIER;
            agent.tool_durability -= 1;
        }
        let node = world.nodes.get_mut(&agent.location).unwrap();
        let amount = node.quantity.min(C::GATHER_AMOUNT * mult);
        node.quantity -= amount;
        agent.add(resource, amount);
        agent.energy = (agent.energy - C::GATHER_ENERGY_COST).max(0.0);
    }
    let after = agent.snapshot();
    entry(tick, agent, "GATHER", Some(target), success, before, after)
}

pub fn resolve_craft(agent: &mut AgentState, _intent: &Intent, tick: i64) -> TickLogEntry {
    let before = agent.snapshot();
    let success = agent.held(ResourceType::Ore) >= C::CRAFT_ORE_COST && agent.held(ResourceType::Wood) >= C::CRAFT_WOOD_COST;
    if success {
        agent.remove(ResourceType::Ore, C::CRAFT_ORE_COST);
        agent.remove(ResourceType::Wood, C::CRAFT_WOOD_COST);
        agent.tool_durability = C::TOOL_DURABILITY;
    }
    let after = agent.snapshot();
    entry(tick, agent, "CRAFT", None, success, before, after)
}

pub fn resolve_consume(agent: &mut AgentState, _intent: &Intent, tick: i64) -> TickLogEntry {
    let before = agent.snapshot();
    let held = agent.held(ResourceType::Food);
    let success = held > 0.0;
    if success {
        let amount = held.min(C::CONSUME_FOOD_PER_ACTION);
        let relief = C::CONSUME_HUNGER_RELIEF * (amount / C::CONSUME_FOOD_PER_ACTION);
        agent.remove(ResourceType::Food, amount);
        agent.hunger = (agent.hunger - relief).max(0.0);
    }
    let after = agent.snapshot();
    entry(tick, agent, "CONSUME", None, success, before, after)
}

pub fn resolve_rest(agent: &mut AgentState, _intent: &Intent, tick: i64) -> TickLogEntry {
    let before = agent.snapshot();
    agent.energy = (agent.energy + C::REST_ENERGY_GAIN).min(100.0);
    let after = agent.snapshot();
    entry(tick, agent, "REST", None, true, before, after)
}

pub fn resolve_signal(agent: &mut AgentState, world: &mut World, intent: &Intent, tick: i64) -> TickLogEntry {
    let before = agent.snapshot();
    let kind = intent.resource.clone().unwrap();
    {
        let node = world.nodes.get_mut(&agent.location).unwrap();
        node.signals.push(Signal { kind: kind.clone(), node_id: node.id.clone(), posted_by: agent.id.clone(), tick });
    }
    let after = agent.snapshot();
    entry(tick, agent, "SIGNAL", Some(kind), true, before, after)
}

fn trade_feasible(agent: &AgentState, partner: Option<&AgentState>, intent: &Intent) -> bool {
    let partner = match partner {
        Some(p) => p,
        None => return false,
    };
    if !partner.alive || partner.location != agent.location {
        return false;
    }
    let give = ResourceType::from_str(intent.give.as_ref().unwrap());
    let want = ResourceType::from_str(intent.want.as_ref().unwrap());
    if agent.held(give) < intent.give_amt {
        return false;
    }
    if partner.held(want) < intent.want_amt {
        return false;
    }
    let partner_receives_value = marginal_value(partner, give);
    let partner_gives_up_value = marginal_value(partner, want);
    partner_receives_value >= partner_gives_up_value
}

fn execute_swap(agent: &mut AgentState, partner: &mut AgentState, intent: &Intent) {
    let give = ResourceType::from_str(intent.give.as_ref().unwrap());
    let want = ResourceType::from_str(intent.want.as_ref().unwrap());
    agent.remove(give, intent.give_amt);
    agent.add(want, intent.want_amt);
    partner.remove(want, intent.want_amt);
    partner.add(give, intent.give_amt);
}

fn two_mut(agents: &mut [AgentState], i: usize, j: usize) -> (&mut AgentState, &mut AgentState) {
    assert_ne!(i, j);
    if i < j {
        let (left, right) = agents.split_at_mut(j);
        (&mut left[i], &mut right[0])
    } else {
        let (left, right) = agents.split_at_mut(i);
        (&mut right[0], &mut left[j])
    }
}

/// Processes all TRADE-intent agents in shuffled order (no first-mover bias).
/// If a swap succeeds, both sides get a log entry from this single resolution,
/// and if the partner's own chosen intent was *also* TRADE, it's marked settled
/// so the outer loop doesn't execute it again as a second, separate swap.
pub fn resolve_trade_phase(
    agents: &mut [AgentState],
    id_to_idx: &HashMap<String, usize>,
    intents: &HashMap<String, Intent>,
    tick: i64,
    rng: &mut impl Rng,
) -> Vec<TickLogEntry> {
    let mut entries = Vec::new();
    let mut initiators: Vec<String> = intents
        .iter()
        .filter(|(aid, intent)| intent.action == "TRADE" && agents[id_to_idx[*aid]].alive)
        .map(|(aid, _)| aid.clone())
        .collect();
    initiators.sort(); // stable base order before shuffling, so shuffle is the only source of randomness
    initiators.shuffle(rng);
    let mut settled: std::collections::HashSet<String> = std::collections::HashSet::new();

    for aid in initiators {
        if settled.contains(&aid) {
            continue;
        }
        let intent = intents.get(&aid).unwrap().clone();
        let target_id = intent.target.clone().unwrap();
        let i = id_to_idx[&aid];

        let j = match id_to_idx.get(&target_id) {
            Some(&j) => j,
            None => continue,
        };
        if i == j {
            continue;
        }

        let (agent, partner) = two_mut(agents, i, j);
        let agent_before = agent.snapshot();
        let partner_before = partner.snapshot();
        let success = trade_feasible(agent, Some(partner), &intent);

        // Phase 5: each side's own valuation of the swap, computed from
        // pre-trade holdings (marginal_value depends on current inventory,
        // so this must happen before execute_swap mutates either agent) -
        // this agent's gain is what it receives valued by its own
        // marginal_value minus what it gives up, valued the same way.
        let give = ResourceType::from_str(intent.give.as_ref().unwrap());
        let want = ResourceType::from_str(intent.want.as_ref().unwrap());
        let agent_gain = marginal_value(agent, want) * intent.want_amt - marginal_value(agent, give) * intent.give_amt;
        let partner_gain = marginal_value(partner, give) * intent.give_amt - marginal_value(partner, want) * intent.want_amt;

        if success {
            execute_swap(agent, partner, &intent);
            agent.record_relationship_trade(&partner.id, agent_gain, tick);
            partner.record_relationship_trade(&agent.id, partner_gain, tick);
        }
        let agent_after = agent.snapshot();
        entries.push(entry(tick, agent, "TRADE", Some(target_id.clone()), success, agent_before, agent_after));

        if success {
            settled.insert(agent.id.clone());
            let partner_after = partner.snapshot();
            let agent_id = agent.id.clone();
            entries.push(entry(tick, partner, "TRADE", Some(agent_id), true, partner_before, partner_after));
            if let Some(pintent) = intents.get(&partner.id) {
                if pintent.action == "TRADE" {
                    settled.insert(partner.id.clone());
                }
            }
        }
    }

    entries
}
