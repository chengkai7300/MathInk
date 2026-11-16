from __future__ import annotations

import math
import os
import threading
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
from .engines.vlm import LlamaServer, VlmEngine
from .image_ops import Point, Stroke

ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = ROOT / "web"
MODEL_DIR = Path(os.environ.get("MATHINK_MODEL_DIR", ROOT / "models" / "comer"))
VLM_DIR = Path(os.environ.get("MATHINK_VLM_DIR", ROOT / "models" / "vlm"))
LLAMA_EXE = Path(
    os.environ.get(
        "MATHINK_LLAMA_EXE",
        ROOT / "tools" / "llama" / "llama-server.exe",
    )
)
VLM_PORT = int(os.environ.get("MATHINK_VLM_PORT", "8849"))

engine: ComerEngine | None = None
vlm: VlmEngine | None = None
vlm_server: LlamaServer | None = None


def _warmup_strokes() -> list[Stroke]:
    return [Stroke(points=[Point(10, 10), Point(60, 10), Point(60, 60), Point(10, 60)], width=3)]


@asynccontextmanager
async def lifespan(app: FastAPI):
    global engine, vlm, vlm_server
    engine = ComerEngine(MODEL_DIR, provider=os.environ.get("MATHINK_PROVIDER", "auto"))
    engine.recognize_strokes(_warmup_strokes())

    vlm_server = LlamaServer(
        exe=LLAMA_EXE,
        model=VLM_DIR / "model-q4km.gguf",
        mmproj=VLM_DIR / "mmproj-q8.gguf",
        port=VLM_PORT,
        log_path=ROOT / "logs" / "llama-server.log",
    )
    vlm = VlmEngine(vlm_server)
    if os.environ.get("MATHINK_VLM", "1") != "0" and vlm.available():
        threading.Thread(target=vlm.warmup, daemon=True).start()

    yield

    if vlm_server is not None:
        vlm_server.stop()
    engine = None


app = FastAPI(title="MathInk", version="0.2.0", lifespan=lifespan)
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
    engine: str = Field(default="auto", pattern="^(auto|comer|vlm)$")


def _to_strokes(req: RecognizeIn) -> list[Stroke]:
    return [
        Stroke(points=[Point(p.x, p.y) for p in s.points], width=s.width)
        for s in req.strokes
    ]


def _confidence(rec) -> float:
    if rec.engine == "vlm" or not rec.tokens:
        return 0.0
    return math.exp(rec.logprob / max(1, len(rec.tokens)))


def _comer_result(rec, total: float) -> dict:
    conf = round(_confidence(rec), 3)
    return {
        "latex": rec.latex,
        "latex_display": latex_utils.to_display(rec.latex),
        "tokens": rec.tokens,
        "valid": latex_utils.is_complete(rec.tokens) and latex_utils.is_balanced(rec.tokens),
        "confidence": conf,
        "logprob": round(rec.logprob, 4),
        "timings": {**rec.timings, "server_total_ms": total},
        "engine": rec.engine,
        "fallback": False,
    }


def _vlm_result(rec, total: float) -> dict:
    return {
        "latex": rec.latex,
        "latex_display": latex_utils.to_display(rec.latex),
        "tokens": rec.tokens,
        "valid": bool(rec.latex),
        "confidence": None,
        "logprob": None,
        "timings": {**rec.timings, "server_total_ms": total},
        "engine": rec.engine,
        "fallback": False,
    }


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "engine": engine.name if engine else None,
        "providers": engine.providers if engine else [],
        "model_dir": str(MODEL_DIR),
        "vlm": {
            "available": bool(vlm and vlm.available()),
            "ready": bool(vlm_server and vlm_server.healthy()),
            "model_dir": str(VLM_DIR),
        },
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
                "note": "CROHME 手写单行公式，CPU，约 0.1–0.4 s",
            },
            {
                "id": "vlm",
                "name": "Uni-MuMER 2B",
                "size_mb": 1550,
                "ready": bool(vlm and vlm.available()),
                "note": "Qwen3-VL 2B 微调，GPU，约 0.5–1.5 s",
            },
        ]
    }


@app.post("/api/recognize")
def recognize(req: RecognizeIn) -> JSONResponse:
    if engine is None:
        raise HTTPException(status_code=503, detail="engine not loaded")
    strokes = _to_strokes(req)
    if not any(s.points for s in strokes):
        raise HTTPException(status_code=400, detail="empty strokes")

    use_vlm = req.engine == "vlm" or (
        req.engine == "auto" and vlm is not None and vlm.available()
    )
    if use_vlm:
        if vlm is None or not vlm.available():
            raise HTTPException(status_code=503, detail="VLM model not installed")
        t0 = time.perf_counter()
        try:
            rec = vlm.recognize_strokes(strokes)
        except Exception as exc:  # keep the API usable if the server fails
            if req.engine == "vlm":
                raise HTTPException(status_code=502, detail=f"VLM error: {exc}") from exc
            rec = None
        if rec is not None:
            total = round((time.perf_counter() - t0) * 1000, 1)
            return JSONResponse(_vlm_result(rec, total))

    t0 = time.perf_counter()
    rec = engine.recognize_strokes(strokes, beam_width=req.beam)
    total = round((time.perf_counter() - t0) * 1000, 1)
    return JSONResponse(_comer_result(rec, total))


if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
