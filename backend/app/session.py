"""Shared session state between input surfaces (tablet pad / desktop host)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Session:
    strokes: list[dict[str, Any]] = field(default_factory=list)
    last_result: dict[str, Any] | None = None
    pads: set[Any] = field(default_factory=set)
    hosts: set[Any] = field(default_factory=set)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    canvas_w: int = 1000
    canvas_h: int = 600

    def canvas(self) -> dict[str, int]:
        return {"w": self.canvas_w, "h": self.canvas_h}

    def state_message(self) -> dict[str, Any]:
        return {"type": "state", "strokes": self.strokes, "canvas": self.canvas()}

    def set_canvas(self, w: int, h: int) -> bool:
        """Resize the logical canvas, scaling existing strokes proportionally."""
        w = max(200, min(2000, int(w)))
        h = max(200, min(2000, int(h)))
        if w == self.canvas_w and h == self.canvas_h:
            return False
        sx = w / self.canvas_w
        sy = h / self.canvas_h
        for s in self.strokes:
            for p in s.get("points", []):
                p["x"] = round(float(p["x"]) * sx, 2)
                p["y"] = round(float(p["y"]) * sy, 2)
            s["width"] = round(float(s.get("width", 3)) * (sx + sy) / 2, 2)
        self.canvas_w, self.canvas_h = w, h
        return True

    async def broadcast(self, message: dict[str, Any], exclude: Any = None) -> None:
        dead = []
        for ws in list(self.pads) + list(self.hosts):
            if ws is exclude:
                continue
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.pads.discard(ws)
            self.hosts.discard(ws)

    async def broadcast_hosts(self, message: dict[str, Any]) -> None:
        dead = []
        for ws in list(self.hosts):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.hosts.discard(ws)
