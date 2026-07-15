"""Crowd agent state and spawning."""

from __future__ import annotations

import random
from dataclasses import dataclass, field

import constants as C
from world import RAW_RESOURCES, ResourceType, World


@dataclass
class AgentState:
    id: str
    location: str
    energy: float
    hunger: float
    specialty: ResourceType
    tier: str = "crowd"
    inventory: dict[str, float] = field(default_factory=dict)
    tool_durability: int = 0
    alive: bool = True
    goal: str = ""         # unused by crowd; leads.py uses this to build a lead's prompt
    personality: str = ""  # unused by crowd; same

    def held(self, resource: ResourceType) -> float:
        return self.inventory.get(resource.value, 0.0)

    def add(self, resource: ResourceType, amount: float) -> None:
        self.inventory[resource.value] = self.held(resource) + amount

    def remove(self, resource: ResourceType, amount: float) -> None:
        self.inventory[resource.value] = max(0.0, self.held(resource) - amount)

    def snapshot(self) -> dict:
        return {
            "location": self.location,
            "energy": round(self.energy, 3),
            "hunger": round(self.hunger, 3),
            "inventory": dict(self.inventory),
            "tool_durability": self.tool_durability,
            "alive": self.alive,
        }


def spawn_agents(num_agents: int, world: World, rng: random.Random) -> list[AgentState]:
    node_ids = list(world.nodes.keys())
    agents = []
    for i in range(num_agents):
        specialty = RAW_RESOURCES[i % len(RAW_RESOURCES)]
        agent = AgentState(
            id=f"a{i}",
            location=rng.choice(node_ids),
            energy=rng.uniform(C.START_ENERGY_MIN, C.START_ENERGY_MAX),
            hunger=rng.uniform(C.START_HUNGER_MIN, C.START_HUNGER_MAX),
            specialty=specialty,
        )
        agents.append(agent)
    return agents
