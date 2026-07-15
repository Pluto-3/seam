//! Crowd agent state and spawning. Ported from `agents.py`.

use rand::Rng;
use serde_json::{json, Value};
use std::collections::HashMap;

use crate::constants as C;
use crate::world::{ResourceType, World, RAW_RESOURCES};

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
        }
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
