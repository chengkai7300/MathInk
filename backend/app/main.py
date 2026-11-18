from __future__ import annotations

import asyncio
import io
import math
import os
import socket
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

import qrcode
from fastapi import (
    FastAPI,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import latex_utils
from .engines.comer import ComerEngine
from .engines.vlm import LlamaServer, VlmEngine
from .image_ops import Point, Stroke
from .session import Session

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
PAD_W, PAD_H = 1000.0, 600.0

engine: ComerEngine | None = None
vlm: VlmEngine | None = None
vlm_server: LlamaServer | None = None
session = Session()
_lan_ip: str | None = None


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


app = FastAPI(title="MathInk", version="0.1.2-test", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class PointIn(BaseModel):
    x: float
    y: float
    pressure: float | None = None


class StrokeIn(BaseModel):
    points: list[PointIn]
    width: float = Field(default=3.0, ge=1, le=24)


class RecognizeIn(BaseModel):
    strokes: list[StrokeIn]
    beam: int | None = Field(default=None, ge=1, le=5)
    engine: str = Field(default="auto", pattern="^(auto|comer|vlm)$")


def _to_strokes(items) -> list[Stroke]:
    return [
        Stroke(points=[Point(p.x, p.y) for p in s.points], width=s.width)
        for s in items
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


# ---------------------------------------------------------------- recognition


def _recognize_sync(strokes: list[Stroke], engine_name: str):
    use_vlm = engine_name == "vlm" or (
        engine_name == "auto" and vlm is not None and vlm.available()
    )
    if use_vlm:
        if vlm is None or not vlm.available():
            raise RuntimeError("VLM model not installed")
        return vlm.recognize_strokes(strokes)
    if engine is None:
        raise RuntimeError("engine not loaded")
    return engine.recognize_strokes(strokes)


async def _recognize_session(engine_name: str, request_id: str | None = None) -> dict | None:
    if not session.strokes:
        return None
    strokes = _to_strokes(_dicts_to_strokes(session.strokes))
    async with session.lock:
        t0 = time.perf_counter()
        rec = await asyncio.to_thread(_recognize_sync, strokes, engine_name)
        total = round((time.perf_counter() - t0) * 1000, 1)
        payload = _vlm_result(rec, total) if rec.engine == "vlm" else _comer_result(rec, total)
    payload["type"] = "result"
    payload["request_id"] = request_id
    session.last_result = payload
    await session.broadcast(payload)
    return payload


# ---------------------------------------------------------------- websockets


def _clean_stroke(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    points = []
    for p in raw.get("points", [])[:4000]:
        try:
            x = float(p.get("x", 0))
            y = float(p.get("y", 0))
        except (TypeError, ValueError):
            continue
        x = min(PAD_W, max(0.0, x))
        y = min(PAD_H, max(0.0, y))
        points.append({"x": round(x, 2), "y": round(y, 2)})
    if not points:
        return None
    try:
        width = float(raw.get("width", 3))
    except (TypeError, ValueError):
        width = 3.0
    width = min(16.0, max(1.0, width))
    return {"points": points, "width": round(width, 2)}


def _dicts_to_strokes(items) -> list:
    out = []
    for s in items:
        pts = [Point(float(p["x"]), float(p["y"])) for p in s.get("points", [])]
        if pts:
            out.append(Stroke(points=pts, width=float(s.get("width", 3))))
    return out


def _apply_viewport(viewport) -> bool:
    """Match the logical canvas aspect to the input device viewport."""
    try:
        vw = float(viewport.get("w", 0))
        vh = float(viewport.get("h", 0))
    except (TypeError, ValueError, AttributeError):
        return False
    if vw <= 0 or vh <= 0:
        return False
    aspect = vw / vh
    if aspect >= 1:
        cw, ch = 1000, round(1000 / aspect)
    else:
        ch, cw = 900, round(900 * aspect)
    cw = max(400, min(1200, int(cw)))
    ch = max(400, min(1200, int(ch)))
    return session.set_canvas(cw, ch)


async def _handle_message(ws: WebSocket, role: str, msg: dict) -> None:
    kind = msg.get("type")
    if kind == "stroke":
        stroke = _clean_stroke(msg.get("stroke"))
        if stroke is None:
            return
        session.strokes.append(stroke)
        if len(session.strokes) > 500:
            session.strokes = session.strokes[-500:]
        await session.broadcast({"type": "stroke", "stroke": stroke}, exclude=ws)
    elif kind == "preview":
        stroke = _clean_stroke(msg.get("stroke")) if msg.get("stroke") else None
        await session.broadcast({"type": "preview", "stroke": stroke}, exclude=ws)
    elif kind == "viewport":
        if _apply_viewport(msg):
            await session.broadcast({"type": "canvas", **session.canvas()})
            await session.broadcast(session.state_message())
    elif kind == "undo":
        if session.strokes:
            session.strokes.pop()
        await session.broadcast(session.state_message())
    elif kind == "clear":
        session.strokes = []
        session.last_result = None
        await session.broadcast(session.state_message())
    elif kind == "recognize":
        try:
            await _recognize_session(msg.get("engine", "auto"), msg.get("request_id"))
        except Exception as exc:
            await session.broadcast({"type": "error", "message": str(exc)})


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    role = "host"
    registered = False
    try:
        hello = await ws.receive_json()
        if isinstance(hello, dict) and hello.get("role") in ("pad", "host"):
            role = hello["role"]
        (session.pads if role == "pad" else session.hosts).add(ws)
        registered = True
        if role == "pad" and isinstance(hello, dict) and hello.get("viewport"):
            if _apply_viewport(hello["viewport"]):
                await session.broadcast({"type": "canvas", **session.canvas()})
        await ws.send_json(session.state_message())
        if session.last_result is not None:
            await ws.send_json(session.last_result)
        await session.broadcast({"type": "peers", "pads": len(session.pads), "hosts": len(session.hosts)})

        while True:
            msg = await ws.receive_json()
            if isinstance(msg, dict):
                await _handle_message(ws, role, msg)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if registered:
            session.pads.discard(ws)
            session.hosts.discard(ws)
            try:
                await session.broadcast(
                    {"type": "peers", "pads": len(session.pads), "hosts": len(session.hosts)}
                )
            except Exception:
                pass


# ---------------------------------------------------------------- HTTP


def _lan_ip_address() -> str:
    global _lan_ip
    if _lan_ip:
        return _lan_ip
    override = os.environ.get("MATHINK_LAN_IP")
    if override:
        _lan_ip = override
        return _lan_ip

    candidates: list[str] = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            candidates.append(info[4][0])
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("192.168.1.1", 80))
            candidates.append(s.getsockname()[0])
        finally:
            s.close()
    except Exception:
        pass

    def score(ip: str) -> int:
        if ip.startswith("192.168."):
            return 0
        if ip.startswith("10."):
            return 1
        if ip.startswith("172."):
            try:
                second = int(ip.split(".")[1])
                if 16 <= second <= 31:
                    return 2
            except ValueError:
                pass
        if ip.startswith("198.18.") or ip.startswith("198.19."):
            return 90
        if ip.startswith("169.254."):
            return 95
        if ip.startswith("127."):
            return 99
        return 50

    unique = [ip for ip in dict.fromkeys(candidates) if ip]
    if unique:
        unique.sort(key=score)
        _lan_ip = unique[0]
    else:
        _lan_ip = "127.0.0.1"
    return _lan_ip


@app.get("/api/lan-info")
def lan_info(request: Request) -> dict:
    port = request.url.port or 8848
    return {"ip": _lan_ip_address(), "port": port, "pad_url": f"http://{_lan_ip_address()}:{port}/pad"}


@app.get("/pad")
def pad_page() -> FileResponse:
    return FileResponse(WEB_DIR / "pad.html")


@app.get("/api/qr.png")
def qr_png(data: str) -> Response:
    if not data or len(data) > 512:
        raise HTTPException(status_code=400, detail="bad data")
    qr = qrcode.QRCode(border=2, box_size=8)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png", headers={"Cache-Control": "no-store"})


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
        "peers": {"pads": len(session.pads), "hosts": len(session.hosts)},
    }


@app.get("/api/engines")
def engines() -> dict:
    return {
        "engines": [
            {
                "id": "vlm",
                "name": "Uni-MuMER 2B",
                "size_mb": 1550,
                "ready": bool(vlm and vlm.available()),
                "note": "GPU，约 60–120 ms",
            },
            {
                "id": "comer",
                "name": "CoMER INT8",
                "size_mb": 7.2,
                "ready": engine is not None,
                "note": "CPU 兜底，约 0.1–0.4 s",
            },
        ]
    }


@app.post("/api/recognize")
def recognize(req: RecognizeIn) -> JSONResponse:
    strokes = _to_strokes(req.strokes)
    if not any(s.points for s in strokes):
        raise HTTPException(status_code=400, detail="empty strokes")
    t0 = time.perf_counter()
    try:
        rec = _recognize_sync(strokes, req.engine)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    total = round((time.perf_counter() - t0) * 1000, 1)
    payload = _vlm_result(rec, total) if rec.engine == "vlm" else _comer_result(rec, total)
    return JSONResponse(payload)


if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
