"""Drawing functions: nodes, edges, agents, HUD. Stateless — takes a pygame
Surface plus whatever world/agent/layout state it needs each frame and draws
it. No simulation logic lives here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pygame

import constants as C
from agents import AgentState
from world import ResourceType, World

BACKGROUND = (18, 18, 24)
EDGE_COLOR = (70, 70, 80)
EDGE_HEAT_COLOR = (255, 160, 60)  # busiest routes fade toward this from EDGE_COLOR
TEXT_COLOR = (230, 230, 230)

SIGNAL_MARKER_COLORS = {
    "order": (255, 215, 0),   # a lead's standing order - the mechanic that was previously invisible
    "scarce": (220, 80, 80),
    "rich": (100, 200, 100),
}
SIGNAL_MARKER_RADIUS = 5

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
# 9 entries as of the interface catch-up pass) both live in this reserved top
# band, so the graph itself is inset below it, not under it. Measured with
# pygame's own font.size() against the actual HUD/legend text rather than
# guessed - see LOG.md. Legend measured at 230px, HUD at 208px; bumped to 280
# for real headroom since more HUD/legend content is still coming this pass
# (event ticker, sparklines) - fixing this properly once, not piecemeal again.
SIDE_MARGIN = 70
TOP_MARGIN = 280
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


def _heat_color(traffic: int, max_traffic: int) -> tuple[int, int, int]:
    if max_traffic <= 0:
        return EDGE_COLOR
    t = min(1.0, traffic / max_traffic)
    return tuple(int(EDGE_COLOR[i] + (EDGE_HEAT_COLOR[i] - EDGE_COLOR[i]) * t) for i in range(3))


def _active_signal_kind(node) -> Optional[str]:
    """At most one marker per node, even if several signal kinds are active at
    once - order takes priority since it's the mechanic that was previously
    invisible; scarce/rich (routine stigmergy) are secondary."""
    kinds = {s.kind.split(":")[0] for s in node.signals}
    for priority in ("order", "scarce", "rich"):
        if priority in kinds:
            return priority
    return None


def draw_world(surface: pygame.Surface, world: World, layout: dict[str, tuple[float, float]],
               screen_size: tuple[int, int], route_traffic: Optional[dict] = None) -> None:
    screen_positions = {node_id: to_screen(pos, screen_size) for node_id, pos in layout.items()}
    route_traffic = route_traffic or {}
    max_traffic = max(route_traffic.values(), default=0)

    drawn_edges = set()
    for node_id, edges in world.adjacency.items():
        for edge in edges:
            key = frozenset((edge.a, edge.b))
            if key in drawn_edges:
                continue
            drawn_edges.add(key)
            if edge.a in screen_positions and edge.b in screen_positions:
                traffic = route_traffic.get(tuple(sorted((edge.a, edge.b))), 0)
                width = 2 + round(5 * (traffic / max_traffic)) if max_traffic > 0 else 2
                pygame.draw.line(surface, _heat_color(traffic, max_traffic),
                                  screen_positions[edge.a], screen_positions[edge.b], width)

    for node_id, node in world.nodes.items():
        pos = screen_positions.get(node_id)
        if pos is None:
            continue
        color = NODE_COLORS.get(node.resource_type, NODE_COLORS[None])
        fill_ratio = (node.quantity / node.max_quantity) if node.max_quantity > 0 else 0.0
        radius = NODE_RADIUS_MIN + (NODE_RADIUS_MAX - NODE_RADIUS_MIN) * max(0.0, min(1.0, fill_ratio))
        pygame.draw.circle(surface, color, pos, int(radius))
        pygame.draw.circle(surface, EDGE_COLOR, pos, int(radius), 2)

        signal_kind = _active_signal_kind(node)
        if signal_kind is not None:
            marker_pos = (pos[0] + int(radius * 0.7), pos[1] - int(radius * 0.7))
            pygame.draw.circle(surface, SIGNAL_MARKER_COLORS[signal_kind], marker_pos, SIGNAL_MARKER_RADIUS)
            pygame.draw.circle(surface, BACKGROUND, marker_pos, SIGNAL_MARKER_RADIUS, 1)


TRADE_EFFECT_DURATION = 0.4   # seconds - wall-clock, not ticks, so effects animate
DEATH_EFFECT_DURATION = 1.2   # at a consistent visual speed regardless of --tps
CRAFT_EFFECT_DURATION = 0.3

TRADE_EFFECT_COLOR = (255, 220, 100)
DEATH_EFFECT_COLOR = (220, 60, 60)
CRAFT_EFFECT_COLOR = (120, 200, 255)


@dataclass
class Effect:
    """A short-lived visual event - a trade, a death, a craft actually
    happening, not a permanent addition to the screen. Positions are in
    layout-space (same coordinates as render_pos/layout), converted to screen
    space at draw time like everything else. created_at is time.monotonic(),
    not a tick number, so effects age at a consistent visual speed no matter
    how fast the simulation itself is running."""
    kind: str  # "trade", "death", "craft"
    pos_a: tuple[float, float]
    created_at: float
    duration: float
    pos_b: Optional[tuple[float, float]] = None  # trade only - the partner's position


def _fade(color: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return tuple(int(color[i] + (BACKGROUND[i] - color[i]) * t) for i in range(3))


def is_effect_expired(effect: Effect, now: float) -> bool:
    return (now - effect.created_at) >= effect.duration


def draw_effects(surface: pygame.Surface, effects: list[Effect], screen_size: tuple[int, int],
                  now: float) -> None:
    for effect in effects:
        age = now - effect.created_at
        if age >= effect.duration:
            continue
        t = age / effect.duration  # 0 = just happened, 1 = fully faded

        if effect.kind == "trade" and effect.pos_b is not None:
            color = _fade(TRADE_EFFECT_COLOR, t)
            pygame.draw.line(surface, color, to_screen(effect.pos_a, screen_size),
                              to_screen(effect.pos_b, screen_size), 2)
        elif effect.kind == "death":
            color = _fade(DEATH_EFFECT_COLOR, t)
            pos = to_screen(effect.pos_a, screen_size)
            radius = int(6 + 22 * t)  # expanding ring
            pygame.draw.circle(surface, color, pos, radius, 2)
        elif effect.kind == "craft":
            color = _fade(CRAFT_EFFECT_COLOR, t)
            pos = to_screen(effect.pos_a, screen_size)
            radius = int(4 + 7 * (1 - abs(2 * t - 1)))  # a quick pulse, grows then shrinks
            pygame.draw.circle(surface, color, pos, max(1, radius))


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
    y += text.get_height() + 4
    for kind, label in (("order", "standing order"), ("scarce", "scarce signal"), ("rich", "rich signal")):
        pygame.draw.circle(surface, SIGNAL_MARKER_COLORS[kind], (x + 8, y + 8), 5)
        text = font.render(label, True, TEXT_COLOR)
        surface.blit(text, (x + 22, y))
        y += text.get_height() + 4


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


HUD_MAX_WIDTH = 585  # measured widest HUD line (trades/crafts/volume/signals) - what actually
                      # matters is staying clear of the legend (starts at w - LEGEND_WIDTH =
                      # 1090 at the current 1300px width), not this number in isolation


TICKER_MAX_LINES = 8
TICKER_WIDTH = 560  # measured: "issues a standing order for wood at n12" is the longest
                     # realistic line at ~522px; this leaves real margin, not guessed
TICKER_BG = (10, 10, 14)


def draw_event_ticker(surface: pygame.Surface, font: pygame.font.Font, lines: list[str],
                       screen_size: tuple[int, int]) -> None:
    """Recent notable events (lead actions, deaths - same filter as
    export_narrative.py) in a small scrolling feed, so glancing away and back
    still tells you what happened, not just what's happening this instant."""
    if not lines:
        return
    _, h = screen_size
    shown = lines[-TICKER_MAX_LINES:]
    line_height = font.get_height() + 3
    box_height = len(shown) * line_height + 10
    box_top = h - BOTTOM_MARGIN - box_height - 10
    box = pygame.Surface((TICKER_WIDTH, box_height))
    box.set_alpha(200)
    box.fill(TICKER_BG)
    surface.blit(box, (SIDE_MARGIN, box_top))
    y = box_top + 5
    for line in shown:
        text = font.render(line, True, TEXT_COLOR)
        surface.blit(text, (SIDE_MARGIN + 8, y))
        y += line_height


SPARKLINE_WIDTH = 180
SPARKLINE_HEIGHT = 36
SPARKLINE_VALUE_GAP = 8


def draw_sparkline(surface: pygame.Surface, font: pygame.font.Font, values, position: tuple[int, int],
                    label: str, color: tuple[int, int, int], value_fmt: str = "{:.0f}") -> int:
    """A compact rolling-history line chart - population and specialization
    index are single numbers in the HUD, which can't show "climbing, flat, or
    dropping since I last looked." Returns the y position just below this
    sparkline, so callers can stack several without hardcoding offsets."""
    x, y = position
    label_surface = font.render(label, True, TEXT_COLOR)
    surface.blit(label_surface, (x, y))
    y += label_surface.get_height() + 2

    if len(values) >= 2:
        lo, hi = min(values), max(values)
        span = (hi - lo) or 1.0
        points = []
        for i, v in enumerate(values):
            px = x + int(i / (len(values) - 1) * SPARKLINE_WIDTH)
            py = y + SPARKLINE_HEIGHT - int((v - lo) / span * SPARKLINE_HEIGHT)
            points.append((px, py))
        pygame.draw.lines(surface, color, False, points, 2)

    if values:
        value_text = font.render(value_fmt.format(values[-1]), True, TEXT_COLOR)
        surface.blit(value_text, (x + SPARKLINE_WIDTH + SPARKLINE_VALUE_GAP,
                                   y + SPARKLINE_HEIGHT // 2 - value_text.get_height() // 2))

    return y + SPARKLINE_HEIGHT + 10


def draw_hud(surface: pygame.Surface, font: pygame.font.Font, *, tick: int, population: int, total: int,
             cumulative_trades: int, cumulative_crafts: int, specialization_idx: float,
             recent_trade_volume: float, signals_active: int,
             paused: bool, ticks_per_second: float, tunable_name: str, tunable_value: float,
             possessed: bool = False) -> None:
    # Kept short and split across lines deliberately - a single wide line here
    # previously ran clean through the legend column (measured 1050px in a 900px
    # window). Each line below is measured to stay under HUD_MAX_WIDTH.
    lines = [
        f"tick {tick}   population {population}/{total} ({total - population} dead)",
        f"trades {cumulative_trades}   crafts {cumulative_crafts}   "
        f"recent volume {recent_trade_volume:.0f}   signals active {signals_active}",
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
