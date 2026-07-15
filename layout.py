"""Screen-position layout for a World's nodes — purely cosmetic, the simulation
itself has no notion of geometry (world.py stays untouched by this).

Circular layout for v1: nodes placed evenly around a circle. Deterministic,
trivial, always readable. A force-directed layout would look nicer but is
real extra complexity — worth it later only if a circle turns out to look
bad with real edge patterns, not before.
"""

from __future__ import annotations

import math

from world import World


def compute_layout(world: World, center: tuple[float, float] = (0.0, 0.0),
                    radius: float = 1.0) -> dict[str, tuple[float, float]]:
    node_ids = list(world.nodes.keys())
    n = len(node_ids)
    positions: dict[str, tuple[float, float]] = {}
    if n == 0:
        return positions
    cx, cy = center
    for i, node_id in enumerate(node_ids):
        angle = 2 * math.pi * i / n
        x = cx + radius * math.cos(angle)
        y = cy + radius * math.sin(angle)
        positions[node_id] = (x, y)
    return positions
