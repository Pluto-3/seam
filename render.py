"""Drawing functions: nodes, edges, agents, HUD. Stateless — takes a pygame
Surface plus whatever world/agent/layout state it needs each frame and draws
it. No simulation logic lives here.
"""

from __future__ import annotations

import pygame

import constants as C
from agents import AgentState
from world import ResourceType, World

BACKGROUND = (18, 18, 24)
EDGE_COLOR = (70, 70, 80)
TEXT_COLOR = (230, 230, 230)

NODE_COLORS = {
    ResourceType.ORE: (150, 150, 160),
    ResourceType.FOOD: (90, 200, 110),
    ResourceType.WOOD: (170, 120, 70),
    None: (90, 90, 100),
}

AGENT_COLORS = {
    ResourceType.ORE: (210, 210, 220),
    ResourceType.FOOD: (140, 230, 150),
    ResourceType.WOOD: (220, 170, 110),
}

NODE_RADIUS_MIN = 8
NODE_RADIUS_MAX = 26
AGENT_RADIUS = 4
EMERGENCY_RING_COLOR = (230, 60, 60)
EMERGENCY_RING_RADIUS = AGENT_RADIUS + 3

RESOURCE_LABELS = {
    ResourceType.ORE: "ore",
    ResourceType.FOOD: "food",
    ResourceType.WOOD: "wood",
}


def is_food_emergency(agent: AgentState) -> bool:
    """Mirrors decide.py's own emergency-routing trigger — an agent this hungry
    with no food in hand is currently BFS-pathfinding toward food rather than
    behaving greedily. Recomputed here from public state, not shared internal
    state, so render.py stays decoupled from decide.py's internals."""
    return agent.hunger >= C.HUNGER_EMERGENCY_THRESHOLD and agent.held(ResourceType.FOOD) < C.TRADE_MIN_HELD


# The HUD (top-left) is 4 lines and the legend (top-right) is a title + 4 entries -
# both live in this top band, so the graph itself is inset below it, not under it.
SIDE_MARGIN = 60
TOP_MARGIN = 140
BOTTOM_MARGIN = 60


def to_screen(pos: tuple[float, float], screen_size: tuple[int, int]) -> tuple[int, int]:
    x, y = pos
    w, h = screen_size
    usable_w = w - 2 * SIDE_MARGIN
    usable_h = h - TOP_MARGIN - BOTTOM_MARGIN
    # layout coords are in [-1, 1] on both axes
    sx = SIDE_MARGIN + (x + 1.0) / 2.0 * usable_w
    sy = TOP_MARGIN + (y + 1.0) / 2.0 * usable_h
    return int(sx), int(sy)


def draw_world(surface: pygame.Surface, world: World, layout: dict[str, tuple[float, float]],
               screen_size: tuple[int, int]) -> None:
    screen_positions = {node_id: to_screen(pos, screen_size) for node_id, pos in layout.items()}

    drawn_edges = set()
    for node_id, edges in world.adjacency.items():
        for edge in edges:
            key = frozenset((edge.a, edge.b))
            if key in drawn_edges:
                continue
            drawn_edges.add(key)
            if edge.a in screen_positions and edge.b in screen_positions:
                pygame.draw.line(surface, EDGE_COLOR, screen_positions[edge.a], screen_positions[edge.b], 2)

    for node_id, node in world.nodes.items():
        pos = screen_positions.get(node_id)
        if pos is None:
            continue
        color = NODE_COLORS.get(node.resource_type, NODE_COLORS[None])
        fill_ratio = (node.quantity / node.max_quantity) if node.max_quantity > 0 else 0.0
        radius = NODE_RADIUS_MIN + (NODE_RADIUS_MAX - NODE_RADIUS_MIN) * max(0.0, min(1.0, fill_ratio))
        pygame.draw.circle(surface, color, pos, int(radius))
        pygame.draw.circle(surface, EDGE_COLOR, pos, int(radius), 2)


def draw_agents(surface: pygame.Surface, agents: list[AgentState],
                 render_pos: dict[str, tuple[float, float]], screen_size: tuple[int, int]) -> None:
    for agent in agents:
        if not agent.alive:
            continue
        pos = render_pos.get(agent.id)
        if pos is None:
            continue
        screen_pos = to_screen(pos, screen_size)
        if is_food_emergency(agent):
            pygame.draw.circle(surface, EMERGENCY_RING_COLOR, screen_pos, EMERGENCY_RING_RADIUS, 1)
        color = AGENT_COLORS.get(agent.specialty, TEXT_COLOR)
        pygame.draw.circle(surface, color, screen_pos, AGENT_RADIUS)


def draw_legend(surface: pygame.Surface, font: pygame.font.Font, screen_size: tuple[int, int]) -> None:
    """Nodes and agent dots share the same color per resource type — this spells
    that out so a viewer isn't expected to just know it."""
    w, _ = screen_size
    x = w - 190
    y = 10
    title = font.render("resource type", True, TEXT_COLOR)
    surface.blit(title, (x, y))
    y += title.get_height() + 4
    for resource, label in RESOURCE_LABELS.items():
        color = NODE_COLORS[resource]
        pygame.draw.circle(surface, color, (x + 8, y + 8), 7)
        text = font.render(label, True, TEXT_COLOR)
        surface.blit(text, (x + 22, y))
        y += text.get_height() + 4
    pygame.draw.circle(surface, EMERGENCY_RING_COLOR, (x + 8, y + 8), 7, 1)
    text = font.render("food emergency", True, TEXT_COLOR)
    surface.blit(text, (x + 22, y))


def draw_hud(surface: pygame.Surface, font: pygame.font.Font, *, tick: int, population: int, total: int,
             cumulative_trades: int, cumulative_crafts: int, specialization_idx: float,
             paused: bool, ticks_per_second: float, tunable_name: str, tunable_value: float) -> None:
    lines = [
        f"tick {tick}   population {population}/{total} alive ({total - population} dead)",
        f"trades {cumulative_trades}   crafts {cumulative_crafts}   "
        f"specialization idx {specialization_idx:.2f}   (0 = no trade effect, higher = more redistribution)",
        f"{'PAUSED' if paused else 'running'}   speed {ticks_per_second:.1f} ticks/s   "
        f"[space] pause  [+/-] speed  [esc] quit",
        f"tunable: {tunable_name} = {tunable_value:.3g}   [tab] cycle  [up/down] adjust 10%",
    ]
    y = 10
    for line in lines:
        text_surface = font.render(line, True, TEXT_COLOR)
        surface.blit(text_surface, (10, y))
        y += text_surface.get_height() + 4
