"""Rolling + cumulative stats over the tick log, printed periodically.

`specialization_index` is the key derived number for the Phase 0 question:
the average fraction of an agent's held raw inventory that is *not* their own
specialty. Trending upward over a run is the clearest evidence that trade is
redistributing goods by need, not noise.
"""

from __future__ import annotations

import csv
from collections import Counter
from typing import Optional

from agents import AgentState
from log import TickLogEntry
from world import RAW_RESOURCES, World


class StatsTracker:
    def __init__(self, csv_path: Optional[str] = None):
        self._trade_leg_count = 0
        self._trade_leg_volume = 0.0
        self.cumulative_crafts = 0

        self._window_trade_leg_count = 0
        self._window_trade_leg_volume = 0.0
        self._window_crafts = 0
        self._window_routes: Counter = Counter()
        self._window_gathers: Counter = Counter()

        self._csv_file = None
        self._csv_writer = None
        if csv_path:
            self._csv_file = open(csv_path, "w", newline="")
            self._csv_writer = csv.writer(self._csv_file)
            self._csv_writer.writerow([
                "tick", "population", "avg_energy", "avg_hunger",
                "avg_ore", "avg_food", "avg_wood",
                "trades_window", "trades_cum",
                "trade_volume_window", "trade_volume_cum",
                "crafts_window", "crafts_cum",
                "signals_active", "specialization_index",
            ])

    def consume(self, entries: list[TickLogEntry]) -> None:
        for e in entries:
            if e.action == "TRADE" and e.success:
                self._trade_leg_count += 1
                self._window_trade_leg_count += 1
                vol = sum(abs(v) for k, v in e.delta.items() if k.startswith("inventory.")) / 2.0
                self._trade_leg_volume += vol
                self._window_trade_leg_volume += vol
            elif e.action == "CRAFT" and e.success:
                self.cumulative_crafts += 1
                self._window_crafts += 1
            elif e.action == "MOVE" and e.success:
                before_loc = e.state_before["location"]
                after_loc = e.state_after["location"]
                route = tuple(sorted((before_loc, after_loc)))
                self._window_routes[route] += 1
            elif e.action == "GATHER" and e.success:
                resource = next((k.split(".")[-1] for k in e.delta if k.startswith("inventory.")), None)
                if resource:
                    self._window_gathers[(e.target, resource)] += 1

    @property
    def cumulative_trades(self) -> int:
        return self._trade_leg_count // 2

    def recent_top_routes(self, n: int = 3) -> list[tuple[tuple[str, str], int]]:
        """Most-traveled routes since the last reset_window() call. Public
        accessor over _window_routes rather than reaching into the private
        attribute directly - same precedent as cumulative_trades."""
        return self._window_routes.most_common(n)

    def route_traffic(self) -> dict[tuple[str, str], int]:
        """The full route->count map since the last reset, not just the top few -
        for a heatmap that needs every edge's relative traffic, not a shortlist."""
        return dict(self._window_routes)

    def recent_top_gathers(self, n: int = 2) -> list[tuple[tuple[str, str], int]]:
        return self._window_gathers.most_common(n)

    def recent_trade_volume(self) -> float:
        return self._window_trade_leg_volume / 2.0

    def signals_active(self, world: World) -> int:
        return sum(len(n.signals) for n in world.nodes.values())

    def reset_window(self) -> None:
        """Starts a fresh 'recent activity' window. snapshot() (run.py's
        periodic printout) already did this inline; watch.py never called it
        at all, so its window counters accumulated for the entire session
        instead of reflecting recent activity - callers that want a rolling
        'recent' view (not just cumulative-since-launch) need to call this
        periodically themselves."""
        self._window_trade_leg_count = 0
        self._window_trade_leg_volume = 0.0
        self._window_crafts = 0
        self._window_routes.clear()
        self._window_gathers.clear()

    def specialization_index(self, agents: list[AgentState]) -> float:
        alive = [a for a in agents if a.alive]
        fractions = []
        for a in alive:
            total = sum(a.held(r) for r in RAW_RESOURCES)
            if total <= 0:
                continue
            non_specialty = total - a.held(a.specialty)
            fractions.append(non_specialty / total)
        return sum(fractions) / len(fractions) if fractions else 0.0

    def snapshot(self, tick: int, agents: list[AgentState], world: World) -> None:
        alive = [a for a in agents if a.alive]
        population = len(alive)
        total = len(agents)
        avg_energy = sum(a.energy for a in alive) / population if population else 0.0
        avg_hunger = sum(a.hunger for a in alive) / population if population else 0.0
        avg_inv = {
            r.value: (sum(a.held(r) for a in alive) / population if population else 0.0)
            for r in RAW_RESOURCES
        }
        signals_active = self.signals_active(world)
        spec_idx = self.specialization_index(agents)

        trades_window = self._window_trade_leg_count // 2
        trades_cum = self._trade_leg_count // 2
        volume_window = self._window_trade_leg_volume / 2.0
        volume_cum = self._trade_leg_volume / 2.0

        top_routes = self._window_routes.most_common(3)
        top_gathers = self._window_gathers.most_common(2)

        print(f"=== tick {tick} ===")
        print(f"population        : {population} / {total} alive ({total - population} dead)")
        print(f"avg energy        : {avg_energy:.1f}")
        print(f"avg hunger        : {avg_hunger:.1f}")
        print("avg inventory     : " + " ".join(f"{k}={v:.2f}" for k, v in avg_inv.items()))
        print(f"trades            : window={trades_window}  cumulative={trades_cum}")
        print(f"trade volume      : window={volume_window:.1f}  cumulative={volume_cum:.1f}")
        print(f"crafts            : window={self._window_crafts}  cumulative={self.cumulative_crafts}")
        print("top routes        : " + " ".join(f"{a}-{b}({n})" for (a, b), n in top_routes))
        print("top gather nodes  : " + " ".join(f"{node}:{res}({n})" for (node, res), n in top_gathers))
        print(f"signals active    : {signals_active}")
        print(f"specialization idx: {spec_idx:.2f}")
        print()

        if self._csv_writer:
            self._csv_writer.writerow([
                tick, population, round(avg_energy, 2), round(avg_hunger, 2),
                round(avg_inv.get("ore", 0.0), 3), round(avg_inv.get("food", 0.0), 3),
                round(avg_inv.get("wood", 0.0), 3),
                trades_window, trades_cum, round(volume_window, 2), round(volume_cum, 2),
                self._window_crafts, self.cumulative_crafts,
                signals_active, round(spec_idx, 3),
            ])
            self._csv_file.flush()

        self.reset_window()

    def close(self) -> None:
        if self._csv_file:
            self._csv_file.close()
