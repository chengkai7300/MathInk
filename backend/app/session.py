"""Shared session state between the tablet pad and the desktop host."""

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

    def state_message(self) -> dict[str, Any]:
        return {"type": "state", "strokes": self.strokes}

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
