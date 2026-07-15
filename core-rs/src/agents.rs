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
        }
    }

    pub fn new_lead(id: String, location: String, energy: f64, hunger: f64, specialty: ResourceType, goal: &str, personality: &str) -> Self {
        let mut a = Self::new(id, location, energy, hunger, specialty);
        a.tier = "lead".to_string();
        a.goal = goal.to_string();
        a.personality = personality.to_string();
        a
    }

    pub fn record_trade_outcome(&mut self, success: bool) {
        self.recent_trades.push_back(success);
        while self.recent_trades.len() > MEMORY_WINDOW {
            self.recent_trades.pop_front();
        }
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
