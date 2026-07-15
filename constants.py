"""Every tunable number for the Phase 0 simulation, in one place.

This is what gets adjusted repeatedly once the first run is in hand — nothing
here is structural, it's all game-balance knobs.
"""

# Defaults for run.py CLI args
NUM_NODES_DEFAULT = 15
NUM_AGENTS_DEFAULT = 40
TICKS_DEFAULT = 2000
STATS_EVERY_DEFAULT = 100

# World generation
NODE_QUANTITY_MIN = 50.0
NODE_QUANTITY_MAX = 150.0
NODE_REGEN_MIN = 1.0
NODE_REGEN_MAX = 5.0
EDGE_COST_MIN = 1.0
EDGE_COST_MAX = 3.0
EXTRA_EDGE_RATIO = 0.5  # extra random edges beyond the spanning tree, as a fraction of num_nodes

# Agent spawn
START_ENERGY_MIN = 70.0
START_ENERGY_MAX = 100.0
START_HUNGER_MIN = 0.0
START_HUNGER_MAX = 30.0

# Metabolism
HUNGER_RATE = 1.0                # per tick, passive
ENERGY_DECAY_RATE = 0.5          # per tick, passive
MOVE_ENERGY_COST_FACTOR = 1.0    # multiplied by edge.cost
GATHER_ENERGY_COST = 0.5
DEATH_HUNGER_MAX = 100.0
DEATH_ENERGY_MIN = 0.0

# Value / scoring
FOOD_BASE_VALUE = 10.0
RAW_BASE_VALUE = 5.0
TOOL_BASE_VALUE = 15.0
CRAFT_COMPLEMENT_BONUS = 4.0     # bonus value for a raw resource when its craft partner is already held

CONSUME_HUNGER_RELIEF = 20.0     # hunger points relieved per Consume action
CONSUME_FOOD_PER_ACTION = 1.0

REST_ENERGY_GAIN = 15.0

SPECIALTY_GATHER_MULTIPLIER = 2.0
OFF_SPECIALTY_GATHER_MULTIPLIER = 0.5
TOOL_GATHER_MULTIPLIER = 1.5
GATHER_AMOUNT = 3.0              # base units gathered per Gather action, before multipliers

CRAFT_ORE_COST = 1.0
CRAFT_WOOD_COST = 1.0
TOOL_DURABILITY = 8              # uses before a crafted tool stops giving a gather bonus

TRADE_UNIT_AMOUNT = 1.0          # fixed amount exchanged per trade, each direction
TRADE_MIN_HELD = 1.0             # minimum held to be willing to give up a unit

SIGNAL_VALUE = 4.0               # must be comparable to typical gather/trade scores (~1-20) to ever win
SIGNAL_MOVE_BONUS = 0.0          # a nudge, not an override — must not dominate the local gather score it's added to
SIGNAL_LOW_THRESHOLD = 0.2       # node quantity / max_quantity at or below this -> "scarce"
SIGNAL_HIGH_THRESHOLD = 0.8      # at or above this -> "rich"
SIGNAL_COOLDOWN = 15             # ticks before the same agent can re-post the same signal kind
SIGNAL_TTL = 30                  # ticks before a signal is pruned

MOVE_LOOKAHEAD_DISCOUNT = 0.85   # per unit of edge cost
JITTER = 0.05                    # +/- 5% random jitter on scores to break brittle ties
