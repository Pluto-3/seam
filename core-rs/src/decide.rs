//! Utility scoring and action selection for crowd agents. Ported from `decide.py`.
//! Greedy "utility AI", no planning/search beyond a 1-hop move lookahead. Every
//! score ultimately derives from marginal_value(): diminishing returns as an
//! agent holds more of something.

use rand::Rng;
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, VecDeque};

use crate::agents::AgentState;
use crate::constants as C;
use crate::world::{Node, ResourceType, World, RAW_RESOURCES};

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Intent {
    pub action: String,
    pub target: Option<String>,
    pub resource: Option<String>,
    pub give: Option<String>,
    pub give_amt: f64,
    pub want: Option<String>,
    pub want_amt: f64,
}

impl Intent {
    pub fn new(action: &str) -> Self {
        Intent {
            action: action.to_string(),
            target: None,
            resource: None,
            give: None,
            give_amt: 0.0,
            want: None,
            want_amt: 0.0,
        }
    }
}

pub fn hunger_pressure(agent: &AgentState) -> f64 {
    (agent.hunger / 100.0).powi(2)
}

pub fn energy_pressure(agent: &AgentState) -> f64 {
    ((100.0 - agent.energy) / 100.0).powi(2)
}

pub fn marginal_value(agent: &AgentState, resource: ResourceType) -> f64 {
    if resource == ResourceType::Tool {
        let held = if agent.tool_durability > 0 { 1.0 } else { 0.0 };
        return C::TOOL_BASE_VALUE / (1.0 + held);
    }
    let held = agent.held(resource);
    let base = if resource == ResourceType::Food {
        C::FOOD_BASE_VALUE * (1.0 + hunger_pressure(agent))
    } else {
        let mut b = C::RAW_BASE_VALUE;
        let other = if resource == ResourceType::Ore { ResourceType::Wood } else { ResourceType::Ore };
        if agent.held(other) >= C::TRADE_MIN_HELD {
            b += C::CRAFT_COMPLEMENT_BONUS;
        }
        b
    };
    base / (1.0 + held)
}

fn gather_yield_multiplier(agent: &AgentState, resource_type: ResourceType) -> f64 {
    let mut mult = if resource_type == agent.specialty {
        C::SPECIALTY_GATHER_MULTIPLIER
    } else {
        C::OFF_SPECIALTY_GATHER_MULTIPLIER
    };
    if agent.tool_durability > 0 {
        mult *= C::TOOL_GATHER_MULTIPLIER;
    }
    mult
}

fn congestion_factor(node_id: &str, agent: &AgentState, node_occupancy: &HashMap<String, i32>) -> f64 {
    let mut count = *node_occupancy.get(node_id).unwrap_or(&0);
    if node_id == agent.location {
        count -= 1;
    }
    1.0 / (1.0 + (count.max(0) as f64) * C::CONGESTION_WEIGHT)
}

fn order_multiplier(node: &Node, resource_type: ResourceType) -> f64 {
    let kind = format!("order:{}", resource_type.as_str());
    if node.signals.iter().any(|s| s.kind == kind) {
        C::ORDER_GATHER_MULTIPLIER
    } else {
        1.0
    }
}

/// First-hop neighbor on the shortest (unweighted) path to the nearest node
/// with food currently available. None if already standing on one, or none
/// is reachable at all.
fn bfs_next_hop_to_food(agent: &AgentState, world: &World) -> Option<String> {
    let start = agent.location.clone();
    let start_node = &world.nodes[&start];
    if start_node.resource_type == Some(ResourceType::Food) && start_node.quantity > 0.0 {
        return None;
    }

    let mut visited: std::collections::HashSet<String> = std::collections::HashSet::new();
    visited.insert(start.clone());

    let mut queue: VecDeque<(String, String)> = VecDeque::new();
    for edge in world.neighbors(&start) {
        let n = edge.other(&start);
        queue.push_back((n.clone(), n));
    }
    for (_, first_hop) in queue.iter() {
        visited.insert(first_hop.clone());
    }

    while let Some((current, first_hop)) = queue.pop_front() {
        let node = &world.nodes[&current];
        if node.resource_type == Some(ResourceType::Food) && node.quantity > 0.0 {
            return Some(first_hop);
        }
        for edge in world.neighbors(&current) {
            let nxt = edge.other(&current);
            if visited.contains(&nxt) {
                continue;
            }
            visited.insert(nxt.clone());
            queue.push_back((nxt, first_hop.clone()));
        }
    }
    None
}

fn can_signal(agent: &AgentState, node: &Node, kind: &str, tick: i64) -> bool {
    !node.signals.iter().any(|s| s.posted_by == agent.id && s.kind == kind && tick - s.tick < C::SIGNAL_COOLDOWN)
}

fn best_local_score(agent: &AgentState, node: &Node, node_occupancy: &HashMap<String, i32>) -> f64 {
    let rt = match node.resource_type {
        Some(r) => r,
        None => return 0.0,
    };
    if node.quantity <= 0.0 {
        return 0.0;
    }
    if agent.held(rt) >= C::MAX_USEFUL_HOLDING {
        return 0.0;
    }
    let mult = gather_yield_multiplier(agent, rt) * order_multiplier(node, rt);
    let congestion = congestion_factor(&node.id, agent, node_occupancy);
    marginal_value(agent, rt) * mult * congestion
}

fn signal_bonus(agent: &AgentState, node: &Node) -> f64 {
    let mut bonus = 0.0;
    let scarce_food = format!("scarce:{}", ResourceType::Food.as_str());
    let scarce_specialty = format!("scarce:{}", agent.specialty.as_str());
    let rich_specialty = format!("rich:{}", agent.specialty.as_str());
    for s in &node.signals {
        if s.kind == scarce_food && agent.held(ResourceType::Food) < C::TRADE_MIN_HELD {
            bonus += C::SIGNAL_MOVE_BONUS;
        }
        if s.kind == scarce_specialty {
            bonus -= C::SIGNAL_MOVE_BONUS;
        }
        if s.kind == rich_specialty {
            bonus += C::SIGNAL_MOVE_BONUS;
        }
    }
    bonus
}

/// Every legal (score, Intent) pair available to an agent this tick.
/// node_occupancy: a node_id -> agent-count snapshot built once per tick.
pub fn generate_candidates(
    agent: &AgentState,
    world: &World,
    colocated: &[&AgentState],
    tick: i64,
    node_occupancy: &HashMap<String, i32>,
    trade_enabled: bool,
) -> Vec<(f64, Intent)> {
    let mut candidates: Vec<(f64, Intent)> = Vec::new();
    let node = &world.nodes[&agent.location];

    // Consume
    let held_food = agent.held(ResourceType::Food);
    if held_food > 0.0 {
        let consumed_fraction = held_food.min(C::CONSUME_FOOD_PER_ACTION) / C::CONSUME_FOOD_PER_ACTION;
        let score = hunger_pressure(agent) * C::CONSUME_HUNGER_RELIEF * consumed_fraction;
        let mut intent = Intent::new("CONSUME");
        intent.resource = Some(ResourceType::Food.as_str().to_string());
        candidates.push((score, intent));
    }

    // Rest
    candidates.push((energy_pressure(agent) * C::REST_ENERGY_GAIN, Intent::new("REST")));

    // Gather
    if let Some(rt) = node.resource_type {
        if node.quantity > 0.0 && agent.held(rt) < C::MAX_USEFUL_HOLDING {
            let mult = gather_yield_multiplier(agent, rt) * order_multiplier(node, rt);
            let congestion = congestion_factor(&node.id, agent, node_occupancy);
            let score = marginal_value(agent, rt) * mult * congestion;
            let mut intent = Intent::new("GATHER");
            intent.target = Some(node.id.clone());
            intent.resource = Some(rt.as_str().to_string());
            candidates.push((score, intent));
        }
    }

    // Craft: 1 ORE + 1 WOOD -> 1 TOOL
    if agent.held(ResourceType::Ore) >= C::CRAFT_ORE_COST && agent.held(ResourceType::Wood) >= C::CRAFT_WOOD_COST {
        let score = marginal_value(agent, ResourceType::Tool)
            - marginal_value(agent, ResourceType::Ore)
            - marginal_value(agent, ResourceType::Wood);
        candidates.push((score, Intent::new("CRAFT")));
    }

    // Trade: mutual benefit is a precondition for even generating the candidate
    if trade_enabled {
        for other in colocated {
            if other.id == agent.id || !other.alive {
                continue;
            }
            for &give in RAW_RESOURCES.iter() {
                if agent.held(give) < C::TRADE_MIN_HELD {
                    continue;
                }
                for &want in RAW_RESOURCES.iter() {
                    if want == give || other.held(want) < C::TRADE_MIN_HELD {
                        continue;
                    }
                    let my_gain = marginal_value(agent, want) - marginal_value(agent, give);
                    let their_gain = marginal_value(other, give) - marginal_value(other, want);
                    if my_gain > 0.0 && their_gain > 0.0 {
                        let mut intent = Intent::new("TRADE");
                        intent.target = Some(other.id.clone());
                        intent.give = Some(give.as_str().to_string());
                        intent.give_amt = C::TRADE_UNIT_AMOUNT;
                        intent.want = Some(want.as_str().to_string());
                        intent.want_amt = C::TRADE_UNIT_AMOUNT;
                        // Memory hook (Phase 2): a lead's accumulated caution discounts
                        // how attractive a trade looks, without changing whether one is
                        // legal at all - still a real, mutually-beneficial trade, just
                        // less eagerly chosen. Zero for crowd agents, so no behavior
                        // change there. Matters even when the LLM doesn't answer in
                        // time, since this feeds the same argmax fallback everyone uses.
                        let discounted = my_gain * (1.0 - agent.caution_bias.clamp(0.0, 0.9));
                        candidates.push((discounted, intent));
                    }
                }
            }
        }
    }

    // Signal (stigmergy): fires when a node crosses a scarcity/abundance threshold
    if node.resource_type.is_some() && node.max_quantity > 0.0 {
        let rt = node.resource_type.unwrap();
        let ratio = node.quantity / node.max_quantity;
        let kind = if ratio <= C::SIGNAL_LOW_THRESHOLD {
            Some(format!("scarce:{}", rt.as_str()))
        } else if ratio >= C::SIGNAL_HIGH_THRESHOLD {
            Some(format!("rich:{}", rt.as_str()))
        } else {
            None
        };
        if let Some(k) = kind {
            if can_signal(agent, node, &k, tick) {
                let mut intent = Intent::new("SIGNAL");
                intent.target = Some(node.id.clone());
                intent.resource = Some(k);
                candidates.push((C::SIGNAL_VALUE, intent));
            }
        }
    }

    // Move: 1-hop lookahead, discounted by edge cost, nudged by signals at the
    // neighbor and, when critically hungry with no food in hand, by a BFS path
    // toward food that the 1-hop lookahead alone could never see.
    let mut emergency_hop: Option<String> = None;
    if agent.hunger >= C::HUNGER_EMERGENCY_THRESHOLD && agent.held(ResourceType::Food) < C::TRADE_MIN_HELD {
        emergency_hop = bfs_next_hop_to_food(agent, world);
    }

    for edge in world.neighbors(&agent.location) {
        let neighbor_id = edge.other(&agent.location);
        let neighbor = &world.nodes[&neighbor_id];
        let local_best = best_local_score(agent, neighbor, node_occupancy);
        let bonus = signal_bonus(agent, neighbor);
        let mut score = local_best * C::MOVE_LOOKAHEAD_DISCOUNT.powf(edge.cost) + bonus;
        if let Some(ref hop) = emergency_hop {
            if *hop == neighbor_id {
                score += C::EMERGENCY_FOOD_BONUS * hunger_pressure(agent);
            }
        }
        let mut intent = Intent::new("MOVE");
        intent.target = Some(neighbor_id);
        candidates.push((score, intent));
    }

    candidates
}

pub fn choose_action(
    agent: &AgentState,
    world: &World,
    colocated: &[&AgentState],
    tick: i64,
    rng: &mut impl Rng,
    node_occupancy: &HashMap<String, i32>,
    trade_enabled: bool,
) -> Intent {
    let candidates = generate_candidates(agent, world, colocated, tick, node_occupancy, trade_enabled);
    if candidates.is_empty() {
        return Intent::new("REST");
    }
    let mut best_score: Option<f64> = None;
    let mut best_intent: Option<Intent> = None;
    for (score, intent) in candidates {
        let jitter = rng.gen_range(-C::JITTER..=C::JITTER);
        let jittered = score * (1.0 + jitter);
        if best_score.is_none() || jittered > best_score.unwrap() {
            best_score = Some(jittered);
            best_intent = Some(intent);
        }
    }
    best_intent.unwrap()
}
