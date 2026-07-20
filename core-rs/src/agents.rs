//! Crowd and lead agent state and spawning. Ported from `agents.py`/`leads.py`.

use rand::Rng;
use serde_json::{json, Value};
use std::collections::{HashMap, VecDeque};

use crate::constants as C;
use crate::world::{ResourceType, World, RAW_RESOURCES};

/// Lead goals + personalities, identical to v1's `leads.py::LEAD_GOALS` -
/// already proven to produce genuinely different behavior per goal.
pub const LEAD_GOALS: [(&str, &str); 3] = [
    ("become the wealthiest trader in the region", "shrewd and opportunistic"),
    ("keep this settlement well stocked on wood", "cautious and protective"),
    ("out-produce every other agent at your specialty", "competitive and driven"),
];

const MEMORY_WINDOW: usize = 20;

#[derive(Clone, Debug)]
pub struct AgentState {
    pub id: String,
    pub location: String,
    pub energy: f64,
    pub hunger: f64,
    pub specialty: ResourceType,
    pub tier: String,
    pub inventory: HashMap<String, f64>,
    pub tool_durability: i32,
    pub alive: bool,
    pub goal: String,
    pub personality: String,

    // Cosmetic identity (crowd: batched at spawn; leads: assigned individually) -
    // absent until the Python sidecar posts one, so early ticks just show the id.
    pub display_name: Option<String>,
    pub blurb: Option<String>,

    // Lead memory (Phase 2): free per-tick counters, plus a periodic LLM
    // self-summary and the one number it's allowed to actually move -
    // caution_bias discounts this agent's own TRADE candidate scores, so
    // memory still matters on ticks the LLM doesn't answer on time.
    pub memory_summary: String,
    pub caution_bias: f64,
    pub recent_trades: VecDeque<bool>, // true = resolved successfully; capped at MEMORY_WINDOW
    pub hunger_scares_witnessed: u32,

    // Phase 5: memory-of-others. Mechanical counters only, all tiers (crowd
    // included) - this is just data, no LLM cost, same reasoning that already
    // justifies caution_bias's mechanical half. Sparse: only grows with real
    // interactions, never a dense N-by-N structure. The LLM-authored
    // *interpretation* of this data (referencing a specific relationship in
    // memory_summary/narrative text) stays lead/hatch-only, since only those
    // tiers get LLM cycles at all - see sidecar.py's build_memory_prompt.
    pub relationships: HashMap<String, RelationshipRecord>,
}

#[derive(Clone, Debug, Default, serde::Serialize)]
pub struct RelationshipRecord {
    pub trades: u32,
    pub trade_balance: f64,        // this agent's net gain/loss across all trades with this partner
    pub contested_node_count: u32, // times both agents gathered at the same node the same tick
    pub orders_followed: u32,      // times this agent's GATHER was boosted by *that* agent's standing order
    pub last_interaction_tick: u64,
}

pub fn round3(v: f64) -> f64 {
    (v * 1000.0).round() / 1000.0
}

impl AgentState {
    pub fn new(id: String, location: String, energy: f64, hunger: f64, specialty: ResourceType) -> Self {
        AgentState {
            id,
            location,
            energy,
            hunger,
            specialty,
            tier: "crowd".to_string(),
            inventory: HashMap::new(),
            tool_durability: 0,
            alive: true,
            goal: String::new(),
            personality: String::new(),
            display_name: None,
            blurb: None,
            memory_summary: String::new(),
            caution_bias: 0.0,
            recent_trades: VecDeque::new(),
            hunger_scares_witnessed: 0,
            relationships: HashMap::new(),
        }
    }

    pub fn new_lead(id: String, location: String, energy: f64, hunger: f64, specialty: ResourceType, goal: &str, personality: &str) -> Self {
        let mut a = Self::new(id, location, energy, hunger, specialty);
        a.tier = "lead".to_string();
        a.goal = goal.to_string();
        a.personality = personality.to_string();
        a
    }

    /// Phase 3: the hatch. Mechanically identical to any other agent - same
    /// action set, same generate_candidates() - the only thing that makes it
    /// "the player" is that nothing ever drives it automatically. It just
    /// sits on crowd-style autopilot until a real POST /player/action arrives.
    pub fn new_player(id: String, location: String, energy: f64, hunger: f64, specialty: ResourceType) -> Self {
        let mut a = Self::new(id, location, energy, hunger, specialty);
        a.tier = "player".to_string();
        a
    }

    pub fn record_trade_outcome(&mut self, success: bool) {
        self.recent_trades.push_back(success);
        while self.recent_trades.len() > MEMORY_WINDOW {
            self.recent_trades.pop_front();
        }
    }

    /// Phase 5: this agent's side of a real, resolved trade with a specific
    /// partner - `my_gain` is this agent's own net inventory value change
    /// from the swap (positive = came out ahead). Only called on success;
    /// a failed trade attempt has no partner-specific relationship to record
    /// (it's not clear who, if anyone, "did" anything to this agent).
    pub fn record_relationship_trade(&mut self, partner_id: &str, my_gain: f64, tick: i64) {
        let rec = self.relationships.entry(partner_id.to_string()).or_default();
        rec.trades += 1;
        rec.trade_balance += my_gain;
        rec.last_interaction_tick = tick.max(0) as u64;
    }

    /// Phase 5: this agent competed for the same gather target, the same
    /// tick, as `other_id` - the mechanical signal the congestion penalty
    /// (`decide.rs::congestion_factor`) already scores but never previously
    /// attributed to specific agents.
    pub fn record_contested_node(&mut self, other_id: &str, tick: i64) {
        let rec = self.relationships.entry(other_id.to_string()).or_default();
        rec.contested_node_count += 1;
        rec.last_interaction_tick = tick.max(0) as u64;
    }

    /// Phase 5: this agent's GATHER just got the order_multiplier boost from
    /// a standing order posted by `poster_id` (a lead or hatch) - the actual
    /// feedback channel. Crowd agents already read a signal's *kind*
    /// (`decide.rs::order_multiplier`) but never its `posted_by`; this is
    /// the first place that identity gets used for anything.
    pub fn record_order_followed(&mut self, poster_id: &str, tick: i64) {
        let rec = self.relationships.entry(poster_id.to_string()).or_default();
        rec.orders_followed += 1;
        rec.last_interaction_tick = tick.max(0) as u64;
    }

    /// Mechanical-only digest of this agent's most significant relationships,
    /// ranked by total interaction weight - no LLM involved, same "the number
    /// is free, the prose costs an LLM call" split as caution_bias. Used for
    /// both the viewer's public_view and the sidecar's relationship digest
    /// that feeds a lead's memory prompt.
    pub fn top_relationships(&self, n: usize) -> Vec<Value> {
        let mut entries: Vec<(&String, &RelationshipRecord)> = self.relationships.iter().collect();
        entries.sort_by(|a, b| {
            let weight_a = a.1.trades + a.1.contested_node_count + a.1.orders_followed;
            let weight_b = b.1.trades + b.1.contested_node_count + b.1.orders_followed;
            weight_b.cmp(&weight_a).then_with(|| b.1.last_interaction_tick.cmp(&a.1.last_interaction_tick))
        });
        entries
            .into_iter()
            .take(n)
            .map(|(other_id, rec)| {
                json!({
                    "other_id": other_id,
                    "trades": rec.trades,
                    "trade_balance": round3(rec.trade_balance),
                    "contested_node_count": rec.contested_node_count,
                    "orders_followed": rec.orders_followed,
                    "last_interaction_tick": rec.last_interaction_tick,
                })
            })
            .collect()
    }

    pub fn trade_success_ratio(&self) -> Option<f64> {
        if self.recent_trades.is_empty() {
            return None;
        }
        let wins = self.recent_trades.iter().filter(|&&s| s).count();
        Some(wins as f64 / self.recent_trades.len() as f64)
    }

    /// Mechanical half of lead memory: caution_bias tracks the free counters
    /// directly, no LLM involved, so it shifts scoring immediately rather than
    /// waiting on a summary call. The LLM-authored memory_summary is the other
    /// half - narrative context fed into future prompts, not the thing that
    /// moves this number. Lead-only: a no-op for crowd agents, so Phase 0/1's
    /// verified crowd behavior is unaffected by this existing on every agent.
    pub fn recompute_caution_bias(&mut self) {
        if self.tier != "lead" {
            return;
        }
        let trade_component = match self.trade_success_ratio() {
            Some(ratio) if self.recent_trades.len() >= 5 => (0.6 - ratio).max(0.0) * 1.2,
            _ => 0.0,
        };
        let hunger_component = (self.hunger_scares_witnessed as f64 * 0.1).min(0.4);
        self.caution_bias = (trade_component + hunger_component).clamp(0.0, 0.9);
    }

    pub fn held(&self, resource: ResourceType) -> f64 {
        *self.inventory.get(resource.as_str()).unwrap_or(&0.0)
    }

    pub fn add(&mut self, resource: ResourceType, amount: f64) {
        let h = self.held(resource);
        self.inventory.insert(resource.as_str().to_string(), h + amount);
    }

    pub fn remove(&mut self, resource: ResourceType, amount: f64) {
        let h = self.held(resource);
        self.inventory.insert(resource.as_str().to_string(), (h - amount).max(0.0));
    }

    /// The tick-log snapshot - deliberately lean (no identity/memory strings),
    /// since this gets embedded in full in every single log entry. Unchanged
    /// from Phase 0/1.
    pub fn snapshot(&self) -> Value {
        json!({
            "location": self.location,
            "energy": round3(self.energy),
            "hunger": round3(self.hunger),
            "inventory": self.inventory,
            "tool_durability": self.tool_durability,
            "alive": self.alive,
        })
    }

    /// The API/viewer view - everything a human or the sidecar would want to
    /// see about this agent right now, including identity and memory. Never
    /// used for tick logging.
    pub fn public_view(&self) -> Value {
        json!({
            "id": self.id,
            "tier": self.tier,
            "display_name": self.display_name,
            "blurb": self.blurb,
            "location": self.location,
            "energy": round3(self.energy),
            "hunger": round3(self.hunger),
            "inventory": self.inventory,
            "alive": self.alive,
            "goal": self.goal,
            "personality": self.personality,
            "memory_summary": self.memory_summary,
            "caution_bias": self.caution_bias,
            "trade_success_ratio": self.trade_success_ratio(),
            "hunger_scares_witnessed": self.hunger_scares_witnessed,
            "top_relationships": self.top_relationships(3),
        })
    }
}

pub fn spawn_leads(world: &World, rng: &mut impl Rng) -> Vec<AgentState> {
    let node_ids = &world.node_order;
    let mut leads = Vec::with_capacity(LEAD_GOALS.len());
    for (i, (goal, personality)) in LEAD_GOALS.iter().enumerate() {
        let specialty = RAW_RESOURCES[i % RAW_RESOURCES.len()];
        let location = node_ids[rng.gen_range(0..node_ids.len())].clone();
        let energy = rng.gen_range(C::START_ENERGY_MIN..=C::START_ENERGY_MAX);
        let hunger = rng.gen_range(C::START_HUNGER_MIN..=C::START_HUNGER_MAX);
        leads.push(AgentState::new_lead(format!("lead{i}"), location, energy, hunger, specialty, goal, personality));
    }
    leads
}

/// v3 Phase 0: one lead per society, starting at that society's home node
/// instead of a random one - everything else (goal/personality assignment,
/// specialty cycling, starting energy/hunger ranges) is identical to
/// `spawn_leads` above, which stays unchanged for the headless `run` binary
/// that has no concept of societies. `locations.len()` is expected to match
/// `LEAD_GOALS.len()` (one lead per society, matching the default society
/// count) - extra locations beyond `LEAD_GOALS.len()` are ignored, since
/// there's no lead goal/personality to assign them yet.
pub fn spawn_leads_at(locations: &[String], rng: &mut impl Rng) -> Vec<AgentState> {
    let mut leads = Vec::with_capacity(locations.len().min(LEAD_GOALS.len()));
    for (i, (goal, personality)) in LEAD_GOALS.iter().enumerate() {
        let location = match locations.get(i) {
            Some(loc) => loc.clone(),
            None => break,
        };
        let specialty = RAW_RESOURCES[i % RAW_RESOURCES.len()];
        let energy = rng.gen_range(C::START_ENERGY_MIN..=C::START_ENERGY_MAX);
        let hunger = rng.gen_range(C::START_HUNGER_MIN..=C::START_HUNGER_MAX);
        leads.push(AgentState::new_lead(format!("lead{i}"), location, energy, hunger, specialty, goal, personality));
    }
    leads
}

pub fn spawn_agents(num_agents: usize, world: &World, rng: &mut impl Rng) -> Vec<AgentState> {
    let node_ids = &world.node_order;
    let mut agents = Vec::with_capacity(num_agents);
    for i in 0..num_agents {
        let specialty = RAW_RESOURCES[i % RAW_RESOURCES.len()];
        let location = node_ids[rng.gen_range(0..node_ids.len())].clone();
        let energy = rng.gen_range(C::START_ENERGY_MIN..=C::START_ENERGY_MAX);
        let hunger = rng.gen_range(C::START_HUNGER_MIN..=C::START_HUNGER_MAX);
        agents.push(AgentState::new(format!("a{i}"), location, energy, hunger, specialty));
    }
    agents
}
