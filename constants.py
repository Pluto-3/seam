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

CONSUME_HUNGER_RELIEF = 20.0     # hunger points relieved by consuming a full CONSUME_FOOD_PER_ACTION unit
CONSUME_FOOD_PER_ACTION = 1.0    # a Consume with less than this held still fires, scaled proportionally —
                                  # an all-or-nothing threshold here strands fractional gathers permanently

REST_ENERGY_GAIN = 15.0

SPECIALTY_GATHER_MULTIPLIER = 2.0
OFF_SPECIALTY_GATHER_MULTIPLIER = 0.5
TOOL_GATHER_MULTIPLIER = 1.5
GATHER_AMOUNT = 3.0              # base units gathered per Gather action, before multipliers
MAX_USEFUL_HOLDING = 25.0        # stop generating a Gather candidate for a resource once held this much —
                                  # without this, an idle agent with nothing better to do keeps gathering
                                  # forever since a shrinking-but-still-positive score still beats a Rest/
                                  # Consume score that's genuinely zero once needs are satisfied

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

# The 1-hop Move lookahead can't see food more than one edge away, which lets an agent
# get topologically stranded (its whole neighborhood is ore/wood) and starve while busily
# gathering/crafting nearby. This is a targeted escape valve, not a general lookahead: once
# hunger crosses the threshold with no food in hand, pathfind (BFS, unweighted) to the
# nearest node with food currently available and bias Move toward the first hop of that path.
HUNGER_EMERGENCY_THRESHOLD = 60.0
EMERGENCY_FOOD_BONUS = 20.0      # scaled by hunger_pressure, so it ramps in rather than snapping on
