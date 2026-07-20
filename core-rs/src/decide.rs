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

// order_strength is a runtime-tunable stand-in for what used to be the fixed
// C::ORDER_GATHER_MULTIPLIER constant - how much a lead/hatch's standing
// order actually biases nearby crowd gathering. Exists so the asymmetric-
// power campaign (DESIGN-V3.md's "Research thread") can vary how much power
// leads/hatches hold over crowd decisions as an experiment variable instead
// of a compile-time constant. Every call site still defaults to the same
// C::ORDER_GATHER_MULTIPLIER value, so behavior is unchanged unless a caller
// deliberately passes something else.
fn order_multiplier(node: &Node, resource_type: ResourceType, order_strength: f64) -> f64 {
    let kind = format!("order:{}", resource_type.as_str());
    if node.signals.iter().any(|s| s.kind == kind) {
        order_strength
    } else {
        1.0
    }
}

/// First-hop neighbor toward the *best* reachable food node - best meaning
/// the highest congestion_factor(node) * MOVE_LOOKAHEAD_DISCOUNT^hops, the
/// same congestion-penalty shape and per-distance discount already used
/// everywhere else in this file, not necessarily the nearest by hop count.
/// The node the agent is already standing on (if it's a food node) is
/// scored by the same formula at hop 0 and competes on equal footing - None
/// means staying put actually won, or nothing is reachable at all, not
/// merely "you happen to already be on some food node." (See below: this
/// used to short-circuit to None the instant the agent was on *any* food
/// node, regardless of how congested or depleted it was - that was the
/// real reason the first version of this fix measured no change at all.)
///
/// Originally returned the *first* food node BFS encountered - nearest by
/// hop count, with zero awareness of how congested it already was. That
/// let a single node become a self-reinforcing trap: once agents started
/// piling onto it, congestion crushed its effective gather success, but
/// every other hungry agent still got routed straight at it anyway, because
/// it was still "nearest with food > 0." Confirmed against real multi-run
/// data (ANALYSIS.md angle 6) before changing this - one node accounted for
/// 42-92% of all activity and 100% of all deaths across three runs, with an
/// 11.5% gather success rate vs. 97-100% at four equally-typed alternatives
/// a few hops away.
///
/// Follow-up (2026-07-18): that first fix (congestion-aware scoring among
/// *reachable* food nodes) was real but incomplete - it never compared
/// against the node the agent was already standing on, so it never fired
/// for the traffic actually driving the hotspot. Fixed here by including
/// "stay" as a scored candidate like everything else. Also confirmed via
/// `decision_debug` (ANALYSIS.md angle 6, 2026-07-18 follow-up) that
/// `best_food_move_score` was null 100% of the time at the hotspot node
/// across ~2.4-3.0M decisions in three independent runs - it has exactly
/// two neighbors and neither is a food node, so the *un-fixed* 1-hop
/// lookahead used for ordinary (non-emergency) MOVE scoring elsewhere in
/// this file structurally cannot see any food alternative from there at
/// all. This function's multi-hop BFS is the only thing that can - which
/// is also why the call site below no longer gates it behind a hunger
/// threshold; see the call site for that half of the fix.
fn bfs_next_hop_to_food(agent: &AgentState, world: &World, node_occupancy: &HashMap<String, i32>) -> Option<String> {
    let start = agent.location.clone();
    let start_node = &world.nodes[&start];

    // Score staying put, if the current node is itself a food node, with the
    // exact same congestion-discounted formula used for every reachable
    // alternative below (dist=0, so no MOVE_LOOKAHEAD_DISCOUNT applied) -
    // makes "should I leave" a real comparison instead of "am I on *any*
    // food node," which was blind to that node's own congestion/quality.
    // That blind spot is why the first version of this fix (b3b8f0e)
    // measured zero real change (87.6% -> 87.5% n13 share): it early-
    // returned None for every agent already standing at n13, so the BFS
    // never even ran for the traffic actually driving n13's dominance.
    let mut best: Option<(Option<String>, f64)> = None; // (first_hop; None = stay put, score)
    if start_node.resource_type == Some(ResourceType::Food) && start_node.quantity > 0.0 {
        best = Some((None, congestion_factor(&start, agent, node_occupancy)));
    }

    let mut visited: std::collections::HashSet<String> = std::collections::HashSet::new();
    visited.insert(start.clone());

    // (node_id, first_hop, hop_distance) - unlike the old version this
    // doesn't return on the first food node found, it keeps searching the
    // whole reachable component (small graph, no need to bound the radius)
    // and scores every candidate found.
    let mut queue: VecDeque<(String, String, u32)> = VecDeque::new();
    for edge in world.neighbors(&start) {
        let n = edge.other(&start);
        queue.push_back((n.clone(), n.clone(), 1));
        visited.insert(n);
    }

    while let Some((current, first_hop, dist)) = queue.pop_front() {
        let node = &world.nodes[&current];
        if node.resource_type == Some(ResourceType::Food) && node.quantity > 0.0 {
            let score = congestion_factor(&current, agent, node_occupancy) * C::MOVE_LOOKAHEAD_DISCOUNT.powf(dist as f64);
            if best.as_ref().map(|(_, s)| score > *s).unwrap_or(true) {
                best = Some((Some(first_hop.clone()), score));
            }
        }
        for edge in world.neighbors(&current) {
            let nxt = edge.other(&current);
            if visited.contains(&nxt) {
                continue;
            }
            visited.insert(nxt.clone());
            queue.push_back((nxt, first_hop.clone(), dist + 1));
        }
    }
    best.and_then(|(hop, _)| hop)
}

fn can_signal(agent: &AgentState, node: &Node, kind: &str, tick: i64) -> bool {
    !node.signals.iter().any(|s| s.posted_by == agent.id && s.kind == kind && tick - s.tick < C::SIGNAL_COOLDOWN)
}

fn best_local_score(agent: &AgentState, node: &Node, node_occupancy: &HashMap<String, i32>, order_strength: f64) -> f64 {
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
    let mult = gather_yield_multiplier(agent, rt) * order_multiplier(node, rt, order_strength);
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
    order_strength: f64,
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
            let mult = gather_yield_multiplier(agent, rt) * order_multiplier(node, rt, order_strength);
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

        // Standing orders: a leadership-only lever (order_multiplier in this
        // same file already reads these to bias crowd gathering) that was
        // never actually reachable through here - the only code path that
        // ever produced one was a manually-constructed Intent posted straight
        // through the hatch's override endpoint. Checked the real decision
        // logs across every run so far: every single SIGNAL a lead ever
        // chose was scarce:/rich:, never order: - not because leads decided
        // against it, but because it was never on the menu. Scored by local
        // urgency (scarcer stock -> more worth ordering) so it's a real
        // contender alongside trade/gather/craft, not a token option nobody
        // would rationally pick.
        if agent.tier == "lead" || agent.tier == "player" {
            let order_kind = format!("order:{}", rt.as_str());
            if can_signal(agent, node, &order_kind, tick) {
                let urgency = (1.0 - ratio).clamp(0.0, 1.0);
                let mut intent = Intent::new("SIGNAL");
                intent.target = Some(node.id.clone());
                intent.resource = Some(order_kind);
                candidates.push((C::SIGNAL_VALUE * (0.5 + urgency), intent));
            }
        }
    }

    // Move: 1-hop lookahead, discounted by edge cost, nudged by signals at the
    // neighbor and, whenever not already holding enough food, by a BFS path
    // toward the best reachable food node (including the agent's current
    // node as a candidate) that the 1-hop lookahead alone could never see.
    //
    // This used to only run past a hunger>=60 "emergency" threshold, which
    // meant it covered under 1% of a hotspot node's real traffic (confirmed
    // via decision_debug, ANALYSIS.md angle 6) - the other 99%+ was ordinary
    // hunger-driven foraging that this BFS never got a chance to inform at
    // all. Dropping the threshold lets it run continuously; its influence
    // still scales up smoothly with hunger via `hunger_pressure` below
    // (quadratic in hunger/100), so a barely-hungry agent gets a negligible
    // nudge and a starving one gets a strong pull - a curve, not a cliff at
    // a fixed hunger value.
    let mut food_bfs_hop: Option<String> = None;
    if agent.held(ResourceType::Food) < C::TRADE_MIN_HELD {
        food_bfs_hop = bfs_next_hop_to_food(agent, world, node_occupancy);
    }

    for edge in world.neighbors(&agent.location) {
        let neighbor_id = edge.other(&agent.location);
        let neighbor = &world.nodes[&neighbor_id];
        let local_best = best_local_score(agent, neighbor, node_occupancy, order_strength);
        let bonus = signal_bonus(agent, neighbor);
        let mut score = local_best * C::MOVE_LOOKAHEAD_DISCOUNT.powf(edge.cost) + bonus;
        if let Some(ref hop) = food_bfs_hop {
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
    order_strength: f64,
) -> Intent {
    choose_action_with_debug(agent, world, colocated, tick, rng, node_occupancy, trade_enabled, order_strength).0
}

/// Decision-time diagnostics for the n13-style congestion-trap investigation
/// (ANALYSIS.md angle 6): the emergency-routing fix turned out to touch only
/// 0.8% of the traffic actually driving a hotspot node's dominance - the
/// other 99.2% is ordinary, non-emergency GATHER-vs-MOVE scoring, and there
/// was no way to see *why* that scoring keeps choosing the congested node
/// short of re-deriving it from raw candidate scores after the fact. These
/// fields make the two live hypotheses (congestion penalty too weak vs.
/// better nodes structurally invisible to a 1-hop lookahead) directly
/// checkable from the log instead of guessed at.
#[derive(Clone, Debug, Serialize)]
pub struct DecisionDebug {
    /// Pre-jitter score of the GATHER-here candidate, if one was generated.
    pub gather_score: Option<f64>,
    /// Pre-jitter score of the single best MOVE candidate, whatever its target.
    pub best_move_score: Option<f64>,
    pub best_move_target: Option<String>,
    /// Pre-jitter score of the best MOVE candidate whose target is itself a
    /// food node - the specific comparison that tests whether a nearby food
    /// alternative was ever competitive, or invisible/losing by construction.
    pub best_food_move_score: Option<f64>,
    pub best_food_move_target: Option<String>,
    /// Pre-jitter score of whichever candidate actually won (post-jitter argmax).
    pub chosen_score: f64,
    pub candidate_count: usize,
    pub location_occupancy: i32,
    pub location_congestion: f64,
    pub hunger: f64,
    pub specialty: String,
    /// Whether this tick's food-held state means the long-range food BFS
    /// (`bfs_next_hop_to_food`) even ran - lets "was multi-hop routing even
    /// in play this tick" be answered directly instead of inferred. No
    /// longer hunger-gated (2026-07-18 follow-up: the BFS itself scales its
    /// influence continuously via hunger_pressure, so this field now tracks
    /// only the food-held guard, not a fixed hunger threshold).
    pub emergency_eligible: bool,
}

pub fn choose_action_with_debug(
    agent: &AgentState,
    world: &World,
    colocated: &[&AgentState],
    tick: i64,
    rng: &mut impl Rng,
    node_occupancy: &HashMap<String, i32>,
    trade_enabled: bool,
    order_strength: f64,
) -> (Intent, DecisionDebug) {
    let candidates = generate_candidates(agent, world, colocated, tick, node_occupancy, trade_enabled, order_strength);

    let gather_score = candidates.iter().find(|(_, i)| i.action == "GATHER").map(|(s, _)| *s);

    let best_move = candidates
        .iter()
        .filter(|(_, i)| i.action == "MOVE")
        .max_by(|a, b| a.0.partial_cmp(&b.0).unwrap());
    let best_move_score = best_move.map(|(s, _)| *s);
    let best_move_target = best_move.and_then(|(_, i)| i.target.clone());

    let best_food_move = candidates
        .iter()
        .filter(|(_, i)| i.action == "MOVE")
        .filter(|(_, i)| {
            i.target
                .as_ref()
                .and_then(|t| world.nodes.get(t))
                .map(|n| n.resource_type == Some(ResourceType::Food))
                .unwrap_or(false)
        })
        .max_by(|a, b| a.0.partial_cmp(&b.0).unwrap());
    let best_food_move_score = best_food_move.map(|(s, _)| *s);
    let best_food_move_target = best_food_move.and_then(|(_, i)| i.target.clone());

    let candidate_count = candidates.len();

    let (chosen_intent, chosen_score) = if candidates.is_empty() {
        (Intent::new("REST"), 0.0)
    } else {
        let mut best_score: Option<f64> = None;
        let mut best_jittered: Option<f64> = None;
        let mut best_intent: Option<Intent> = None;
        for (score, intent) in candidates {
            let jitter = rng.gen_range(-C::JITTER..=C::JITTER);
            let jittered = score * (1.0 + jitter);
            if best_jittered.is_none() || jittered > best_jittered.unwrap() {
                best_jittered = Some(jittered);
                best_score = Some(score);
                best_intent = Some(intent);
            }
        }
        (best_intent.unwrap(), best_score.unwrap())
    };

    let debug = DecisionDebug {
        gather_score,
        best_move_score,
        best_move_target,
        best_food_move_score,
        best_food_move_target,
        chosen_score,
        candidate_count,
        location_occupancy: *node_occupancy.get(&agent.location).unwrap_or(&0),
        location_congestion: congestion_factor(&agent.location, agent, node_occupancy),
        hunger: agent.hunger,
        specialty: agent.specialty.as_str().to_string(),
        emergency_eligible: agent.held(ResourceType::Food) < C::TRADE_MIN_HELD,
    };

    (chosen_intent, debug)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// start -o- near (food, 1 hop) and start -o- mid -o- far (food, 2 hops).
    /// The first bfs_next_hop_to_food test this function has ever had -
    /// nothing existing to preserve, but the two cases that actually matter
    /// for the fix: unchanged behavior when there's nothing to route
    /// around, and the new behavior (routing past a nearer-but-congested
    /// node) when there is.
    fn two_food_node_world() -> World {
        let mut w = World::new();
        w.add_node(Node { id: "start".into(), resource_type: Some(ResourceType::Ore), quantity: 10.0, max_quantity: 10.0, regen_rate: 0.0, signals: vec![] });
        w.add_node(Node { id: "near".into(), resource_type: Some(ResourceType::Food), quantity: 10.0, max_quantity: 10.0, regen_rate: 0.0, signals: vec![] });
        w.add_node(Node { id: "mid".into(), resource_type: Some(ResourceType::Ore), quantity: 10.0, max_quantity: 10.0, regen_rate: 0.0, signals: vec![] });
        w.add_node(Node { id: "far".into(), resource_type: Some(ResourceType::Food), quantity: 10.0, max_quantity: 10.0, regen_rate: 0.0, signals: vec![] });
        w.add_edge("start", "near", 1.0);
        w.add_edge("start", "mid", 1.0);
        w.add_edge("mid", "far", 1.0);
        w
    }

    fn hungry_agent() -> AgentState {
        AgentState::new("a0".into(), "start".into(), 50.0, 90.0, ResourceType::Ore)
    }

    #[test]
    fn picks_nearer_food_node_when_uncongested() {
        let world = two_food_node_world();
        let agent = hungry_agent();
        let occupancy: HashMap<String, i32> = HashMap::new();
        // "near" (1 hop) should beat "far" (2 hops) when nothing is congested -
        // same behavior as before this fix, not just a new one.
        assert_eq!(bfs_next_hop_to_food(&agent, &world, &occupancy), Some("near".to_string()));
    }

    #[test]
    fn routes_around_a_congested_nearer_node() {
        let world = two_food_node_world();
        let agent = hungry_agent();
        let mut occupancy: HashMap<String, i32> = HashMap::new();
        // Heavy congestion at the nearer food node should push the agent
        // toward the farther-but-clear one instead - the actual bug fix.
        occupancy.insert("near".to_string(), 20);
        assert_eq!(bfs_next_hop_to_food(&agent, &world, &occupancy), Some("mid".to_string()));
    }

    #[test]
    fn stays_on_an_uncongested_food_node_with_no_better_alternative() {
        let world = two_food_node_world();
        let mut agent = hungry_agent();
        agent.location = "near".to_string();
        let occupancy: HashMap<String, i32> = HashMap::new();
        // "near" is uncongested (score 1.0) and "far" is 3 hops away from
        // here (near -> start -> mid -> far, discount 0.85^3 = 0.614) - not
        // worth leaving for, so staying correctly wins.
        assert_eq!(bfs_next_hop_to_food(&agent, &world, &occupancy), None);
    }

    #[test]
    fn leaves_a_congested_food_node_for_a_better_reachable_one() {
        let world = two_food_node_world();
        let mut agent = hungry_agent();
        agent.location = "near".to_string();
        let mut occupancy: HashMap<String, i32> = HashMap::new();
        // The actual 2026-07-18 fix: previously this returned None
        // unconditionally just for being on *a* food node, never comparing
        // against how congested it already was. Now heavy congestion at
        // "near" (score 1/(1+20*0.3) = 0.143) should lose to the clear
        // "far" node reachable via "start" (score 0.85^3 = 0.614), and the
        // agent should route away from its own congested node.
        occupancy.insert("near".to_string(), 20);
        assert_eq!(bfs_next_hop_to_food(&agent, &world, &occupancy), Some("start".to_string()));
    }
}
