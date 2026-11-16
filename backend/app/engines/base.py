from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Recognition:
    latex: str
    tokens: list[str] = field(default_factory=list)
    logprob: float = 0.0
    timings: dict[str, float] = field(default_factory=dict)
    engine: str = "comer"
