//! World graph: nodes with resources, edges with travel cost, node-local signals.
//! Ported from `world.py`.

use rand::Rng;
use std::collections::{HashMap, HashSet};

use crate::constants as C;

#[derive(Clone, Copy, PartialEq, Eq, Debug, Hash)]
pub enum ResourceType {
    Ore,
    Food,
    Wood,
    Tool,
}

impl ResourceType {
    pub fn as_str(&self) -> &'static str {
        match self {
            ResourceType::Ore => "ore",
            ResourceType::Food => "food",
            ResourceType::Wood => "wood",
            ResourceType::Tool => "tool",
        }
    }

    pub fn from_str(s: &str) -> ResourceType {
        match s {
            "ore" => ResourceType::Ore,
            "food" => ResourceType::Food,
            "wood" => ResourceType::Wood,
            "tool" => ResourceType::Tool,
            other => panic!("unknown resource type: {other}"),
        }
    }
}

pub const RAW_RESOURCES: [ResourceType; 3] = [ResourceType::Ore, ResourceType::Food, ResourceType::Wood];

#[derive(Clone, Debug)]
pub struct Signal {
    pub kind: String,
    pub node_id: String,
    pub posted_by: String,
    pub tick: i64,
}

#[derive(Clone, Debug)]
pub struct Node {
    pub id: String,
    pub resource_type: Option<ResourceType>,
    pub quantity: f64,
    pub max_quantity: f64,
    pub regen_rate: f64,
    pub signals: Vec<Signal>,
}

#[derive(Clone, Debug)]
pub struct Edge {
    pub a: String,
    pub b: String,
    pub cost: f64,
}

impl Edge {
    pub fn other(&self, node_id: &str) -> String {
        if node_id == self.a {
            self.b.clone()
        } else {
            self.a.clone()
        }
    }
}

pub struct World {
    pub nodes: HashMap<String, Node>,
    pub node_order: Vec<String>,
    pub adjacency: HashMap<String, Vec<Edge>>,
}

impl World {
    pub fn new() -> Self {
        World {
            nodes: HashMap::new(),
            node_order: Vec::new(),
            adjacency: HashMap::new(),
        }
    }

    pub fn add_node(&mut self, node: Node) {
        let id = node.id.clone();
        self.node_order.push(id.clone());
        self.adjacency.entry(id.clone()).or_insert_with(Vec::new);
        self.nodes.insert(id, node);
    }

    pub fn add_edge(&mut self, a: &str, b: &str, cost: f64) {
        let edge = Edge { a: a.to_string(), b: b.to_string(), cost };
        self.adjacency.get_mut(a).unwrap().push(edge.clone());
        self.adjacency.get_mut(b).unwrap().push(edge);
    }

    pub fn neighbors(&self, node_id: &str) -> &[Edge] {
        self.adjacency.get(node_id).map(|v| v.as_slice()).unwrap_or(&[])
    }

    pub fn regen(&mut self) {
        for node in self.nodes.values_mut() {
            if node.resource_type.is_none() {
                continue;
            }
            node.quantity = (node.quantity + node.regen_rate).min(node.max_quantity);
        }
    }

    pub fn prune_signals(&mut self, tick: i64) {
        for node in self.nodes.values_mut() {
            node.signals.retain(|s| tick - s.tick <= C::SIGNAL_TTL);
        }
    }

    pub fn is_connected(&self) -> bool {
        if self.nodes.is_empty() {
            return true;
        }
        let start = self.node_order[0].clone();
        let mut seen: HashSet<String> = HashSet::new();
        seen.insert(start.clone());
        let mut stack = vec![start];
        while let Some(current) = stack.pop() {
            for edge in self.neighbors(&current) {
                let nxt = edge.other(&current);
                if !seen.contains(&nxt) {
                    seen.insert(nxt.clone());
                    stack.push(nxt);
                }
            }
        }
        seen.len() == self.nodes.len()
    }
}

pub fn generate_world(num_nodes: usize, rng: &mut impl Rng) -> World {
    let mut world = World::new();
    let node_ids: Vec<String> = (0..num_nodes).map(|i| format!("n{i}")).collect();

    for (i, node_id) in node_ids.iter().enumerate() {
        let resource_type = RAW_RESOURCES[i % RAW_RESOURCES.len()];
        let max_q = rng.gen_range(C::NODE_QUANTITY_MIN..=C::NODE_QUANTITY_MAX);
        let regen_rate = rng.gen_range(C::NODE_REGEN_MIN..=C::NODE_REGEN_MAX);
        world.add_node(Node {
            id: node_id.clone(),
            resource_type: Some(resource_type),
            quantity: max_q,
            max_quantity: max_q,
            regen_rate,
            signals: Vec::new(),
        });
    }

    // random recursive tree: connect each node to a random earlier node -> guarantees connectivity
    for i in 1..num_nodes {
        let j = rng.gen_range(0..i);
        let cost = rng.gen_range(C::EDGE_COST_MIN..=C::EDGE_COST_MAX);
        world.add_edge(&node_ids[i], &node_ids[j], cost);
    }

    // extra random edges so routing has real choices
    let extra = (num_nodes as f64 * C::EXTRA_EDGE_RATIO) as usize;
    let mut existing: HashSet<(String, String)> = HashSet::new();
    for edges in world.adjacency.values() {
        for e in edges {
            let key = if e.a <= e.b { (e.a.clone(), e.b.clone()) } else { (e.b.clone(), e.a.clone()) };
            existing.insert(key);
        }
    }
    let mut added = 0;
    let mut attempts = 0;
    while added < extra && attempts < extra * 10 && num_nodes > 2 {
        attempts += 1;
        let idx = rand::seq::index::sample(rng, node_ids.len(), 2).into_vec();
        let (a, b) = (node_ids[idx[0]].clone(), node_ids[idx[1]].clone());
        let key = if a <= b { (a.clone(), b.clone()) } else { (b.clone(), a.clone()) };
        if existing.contains(&key) {
            continue;
        }
        let cost = rng.gen_range(C::EDGE_COST_MIN..=C::EDGE_COST_MAX);
        world.add_edge(&a, &b, cost);
        existing.insert(key);
        added += 1;
    }

    world
}
