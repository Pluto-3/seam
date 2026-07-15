//! Every tunable number for the Phase 0 simulation, ported 1:1 from `constants.py`.
//! Values must match the Python source exactly - this is a port, not a retune.

// World generation
pub const NODE_QUANTITY_MIN: f64 = 50.0;
pub const NODE_QUANTITY_MAX: f64 = 150.0;
pub const NODE_REGEN_MIN: f64 = 1.0;
pub const NODE_REGEN_MAX: f64 = 5.0;
pub const EDGE_COST_MIN: f64 = 1.0;
pub const EDGE_COST_MAX: f64 = 3.0;
pub const EXTRA_EDGE_RATIO: f64 = 0.5;

// Agent spawn
pub const START_ENERGY_MIN: f64 = 70.0;
pub const START_ENERGY_MAX: f64 = 100.0;
pub const START_HUNGER_MIN: f64 = 0.0;
pub const START_HUNGER_MAX: f64 = 30.0;

// Metabolism
pub const HUNGER_RATE: f64 = 1.0;
pub const ENERGY_DECAY_RATE: f64 = 0.5;
pub const MOVE_ENERGY_COST_FACTOR: f64 = 1.0;
pub const GATHER_ENERGY_COST: f64 = 0.5;
pub const DEATH_HUNGER_MAX: f64 = 100.0;
pub const DEATH_ENERGY_MIN: f64 = 0.0;

// Value / scoring
pub const FOOD_BASE_VALUE: f64 = 10.0;
pub const RAW_BASE_VALUE: f64 = 5.0;
pub const TOOL_BASE_VALUE: f64 = 15.0;
pub const CRAFT_COMPLEMENT_BONUS: f64 = 4.0;

pub const CONSUME_HUNGER_RELIEF: f64 = 20.0;
pub const CONSUME_FOOD_PER_ACTION: f64 = 1.0;

pub const REST_ENERGY_GAIN: f64 = 15.0;

pub const SPECIALTY_GATHER_MULTIPLIER: f64 = 2.0;
pub const OFF_SPECIALTY_GATHER_MULTIPLIER: f64 = 0.5;
pub const TOOL_GATHER_MULTIPLIER: f64 = 1.5;
pub const GATHER_AMOUNT: f64 = 3.0;
pub const MAX_USEFUL_HOLDING: f64 = 25.0;

pub const CRAFT_ORE_COST: f64 = 1.0;
pub const CRAFT_WOOD_COST: f64 = 1.0;
pub const TOOL_DURABILITY: i32 = 8;

pub const TRADE_UNIT_AMOUNT: f64 = 1.0;
pub const TRADE_MIN_HELD: f64 = 1.0;

pub const SIGNAL_VALUE: f64 = 4.0;
pub const SIGNAL_MOVE_BONUS: f64 = 0.0;
pub const ORDER_GATHER_MULTIPLIER: f64 = 1.6;

pub const CONGESTION_WEIGHT: f64 = 0.3;
pub const SIGNAL_LOW_THRESHOLD: f64 = 0.2;
pub const SIGNAL_HIGH_THRESHOLD: f64 = 0.8;
pub const SIGNAL_COOLDOWN: i64 = 15;
pub const SIGNAL_TTL: i64 = 30;

pub const MOVE_LOOKAHEAD_DISCOUNT: f64 = 0.85;
pub const JITTER: f64 = 0.05;

pub const HUNGER_EMERGENCY_THRESHOLD: f64 = 60.0;
pub const EMERGENCY_FOOD_BONUS: f64 = 20.0;
