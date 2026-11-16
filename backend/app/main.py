from __future__ import annotations

import math
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import latex_utils
from .engines.comer import ComerEngine
from .image_ops import Point, Stroke

ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = ROOT / "web"
MODEL_DIR = Path(os.environ.get("MATHINK_MODEL_DIR", ROOT / "models" / "comer"))

engine: ComerEngine | None = None


def _warmup_strokes() -> list[Stroke]:
    return [Stroke(points=[Point(10, 10), Point(60, 10), Point(60, 60), Point(10, 60)], width=3)]


@asynccontextmanager
async def lifespan(app: FastAPI):
    global engine
    engine = ComerEngine(MODEL_DIR, provider=os.environ.get("MATHINK_PROVIDER", "auto"))
    engine.recognize_strokes(_warmup_strokes())
    yield
    engine = None


app = FastAPI(title="MathInk", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class PointIn(BaseModel):
    x: float
    y: float


class StrokeIn(BaseModel):
    points: list[PointIn]
    width: float = Field(default=3.0, ge=1, le=24)


class RecognizeIn(BaseModel):
    strokes: list[StrokeIn]
    beam: int | None = Field(default=None, ge=1, le=5)
    engine: str | None = None


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "engine": engine.name if engine else None,
        "providers": engine.providers if engine else [],
        "model_dir": str(MODEL_DIR),
    }


@app.get("/api/engines")
def engines() -> dict:
    return {
        "engines": [
            {
                "id": "comer",
                "name": "CoMER INT8",
                "size_mb": 7.2,
                "ready": engine is not None,
                "note": "CROHME 手写单行公式，CPU 可跑",
            }
        ]
    }


@app.post("/api/recognize")
def recognize(req: RecognizeIn) -> JSONResponse:
    if engine is None:
        raise HTTPException(status_code=503, detail="engine not loaded")
    strokes = [
        Stroke(points=[Point(p.x, p.y) for p in s.points], width=s.width)
        for s in req.strokes
    ]
    if not any(s.points for s in strokes):
        raise HTTPException(status_code=400, detail="empty strokes")

    t0 = time.perf_counter()
    rec = engine.recognize_strokes(strokes, beam_width=req.beam)
    total = round((time.perf_counter() - t0) * 1000, 1)
    confidence = (
        round(math.exp(rec.logprob / max(1, len(rec.tokens))), 3) if rec.tokens else 0.0
    )

    return JSONResponse(
        {
            "latex": rec.latex,
            "latex_display": latex_utils.to_display(rec.latex),
            "tokens": rec.tokens,
            "valid": latex_utils.is_complete(rec.tokens)
            and latex_utils.is_balanced(rec.tokens),
            "confidence": confidence,
            "logprob": round(rec.logprob, 4),
            "timings": {**rec.timings, "server_total_ms": total},
            "engine": rec.engine,
        }
    )


if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
