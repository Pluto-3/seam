"""Tick log entries and a generic before/after diff.

One diff() function handles every action — no per-action special-casing.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Optional


@dataclass
class TickLogEntry:
    tick: int
    agent_id: str
    tier: str
    state_before: dict
    action: str
    target: Optional[str]
    success: bool
    state_after: dict
    delta: dict

    def to_json(self) -> str:
        return json.dumps(asdict(self))


def diff(before: dict, after: dict) -> dict:
    """Flat diff of two agent snapshot dicts; only reports changed keys.

    Inventory is diffed sub-key by sub-key (inventory.<resource>). Booleans are
    handled explicitly before the numeric branch, since bool is a subclass of
    int in Python and would otherwise turn `alive: False` into `alive: -1`.
    """
    changes: dict[str, Any] = {}
    for key in after:
        if key == "inventory":
            inv_before = before.get("inventory", {})
            inv_after = after.get("inventory", {})
            for res in set(inv_before) | set(inv_after):
                b = inv_before.get(res, 0.0)
                a = inv_after.get(res, 0.0)
                if abs(a - b) > 1e-9:
                    changes[f"inventory.{res}"] = round(a - b, 3)
            continue

        b = before.get(key)
        a = after.get(key)
        if a == b:
            continue
        if isinstance(a, bool) or isinstance(b, bool):
            changes[key] = a
        elif isinstance(a, (int, float)) and isinstance(b, (int, float)):
            changes[key] = round(a - b, 3)
        else:
            changes[key] = a
    return changes


class JsonlWriter:
    def __init__(self, path: str):
        self._file = open(path, "w")

    def write(self, entry: TickLogEntry) -> None:
        self._file.write(entry.to_json() + "\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()
