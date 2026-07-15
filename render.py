"""Drawing functions: nodes, edges, agents, HUD. Stateless — takes a pygame
Surface plus whatever world/agent/layout state it needs each frame and draws
it. No simulation logic lives here.
"""

from __future__ import annotations

from typing import Optional

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

LEAD_RADIUS = 7                    # larger than a crowd dot - "visually findable" per the Phase 2 plan
LEAD_RING_COLOR = (230, 190, 60)   # gold ring around a lead's specialty-colored dot
PLAYER_RADIUS = 8
PLAYER_RING_COLOR_AUTOPILOT = (100, 200, 230)   # thin ring - the hatch, idling
PLAYER_RING_COLOR_POSSESSED = (255, 255, 255)   # thick bright ring - actively driven

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


# The HUD (top-left, up to 9 lines once possessed) and legend (top-right, title +
# 6 entries) both live in this reserved top band, so the graph itself is inset
# below it, not under it. Measured with pygame's own font.size() against the
# actual HUD/legend text rather than guessed - see LOG.md. HUD height measured
# at 208px with the hatch keymap line showing; 240 leaves real headroom.
SIDE_MARGIN = 70
TOP_MARGIN = 240
BOTTOM_MARGIN = 70


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
                 render_pos: dict[str, tuple[float, float]], screen_size: tuple[int, int], *,
                 player_agent_id: Optional[str] = None, possessed: bool = False) -> None:
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

        if agent.id == player_agent_id:
            ring_color = PLAYER_RING_COLOR_POSSESSED if possessed else PLAYER_RING_COLOR_AUTOPILOT
            ring_width = 3 if possessed else 1
            pygame.draw.circle(surface, ring_color, screen_pos, PLAYER_RADIUS, ring_width)
            pygame.draw.circle(surface, color, screen_pos, AGENT_RADIUS)
        elif agent.tier == "lead":
            pygame.draw.circle(surface, LEAD_RING_COLOR, screen_pos, LEAD_RADIUS, 2)
            pygame.draw.circle(surface, color, screen_pos, AGENT_RADIUS)
        else:
            pygame.draw.circle(surface, color, screen_pos, AGENT_RADIUS)


LEGEND_WIDTH = 210  # measured: "food emergency" label is ~140px, plus swatch and padding


def draw_legend(surface: pygame.Surface, font: pygame.font.Font, screen_size: tuple[int, int]) -> None:
    """Nodes and agent dots share the same color per resource type — this spells
    that out so a viewer isn't expected to just know it."""
    w, _ = screen_size
    x = w - LEGEND_WIDTH
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
    y += text.get_height() + 4
    pygame.draw.circle(surface, LEAD_RING_COLOR, (x + 8, y + 8), 7, 2)
    text = font.render("lead", True, TEXT_COLOR)
    surface.blit(text, (x + 22, y))
    y += text.get_height() + 4
    pygame.draw.circle(surface, PLAYER_RING_COLOR_POSSESSED, (x + 8, y + 8), 7, 2)
    text = font.render("you (hatch)", True, TEXT_COLOR)
    surface.blit(text, (x + 22, y))


def draw_player_moves(surface: pygame.Surface, font: pygame.font.Font, world: World,
                       player_location: str, layout: dict[str, tuple[float, float]],
                       screen_size: tuple[int, int]) -> list[str]:
    """Draws a number label near each neighbor of the player's current node, and
    returns the ordered list of neighbor node ids so watch.py can map a number
    key back to a specific move target. Only meaningful while possessed."""
    neighbor_ids = [edge.other(player_location) for edge in world.neighbors(player_location)]
    for i, neighbor_id in enumerate(neighbor_ids[:9]):
        pos = to_screen(layout[neighbor_id], screen_size)
        label = font.render(str(i + 1), True, (255, 255, 0))
        surface.blit(label, (pos[0] - 6, pos[1] - 26))
    return neighbor_ids


HUD_MAX_WIDTH = 570  # measured widest HUD line (the possessed keymap hint) - what actually
                      # matters is staying clear of the legend (starts at w - LEGEND_WIDTH =
                      # 1090 at the current 1300px width), not this number in isolation


def draw_hud(surface: pygame.Surface, font: pygame.font.Font, *, tick: int, population: int, total: int,
             cumulative_trades: int, cumulative_crafts: int, specialization_idx: float,
             paused: bool, ticks_per_second: float, tunable_name: str, tunable_value: float,
             possessed: bool = False) -> None:
    # Kept short and split across lines deliberately - a single wide line here
    # previously ran clean through the legend column (measured 1050px in a 900px
    # window). Each line below is measured to stay under HUD_MAX_WIDTH.
    lines = [
        f"tick {tick}   population {population}/{total} ({total - population} dead)",
        f"trades {cumulative_trades}   crafts {cumulative_crafts}",
        f"specialization idx {specialization_idx:.2f}  (higher = more trade)",
        f"{'PAUSED' if paused else 'running'}   speed {ticks_per_second:.1f} ticks/s",
        "[space] pause   [+/-] speed   [esc] quit",
        f"tunable: {tunable_name} = {tunable_value:.3g}",
        "[tab] cycle   [up/down] adjust 10%",
        f"hatch: {'POSSESSED (you)' if possessed else 'autopilot'}   [p] possess/release",
    ]
    if possessed:
        lines.append("[1-9] move  [g]ather [c]onsume [f]craft [r]est [t]rade [x]order")
    y = 10
    for line in lines:
        text_surface = font.render(line, True, TEXT_COLOR)
        surface.blit(text_surface, (10, y))
        y += text_surface.get_height() + 4
