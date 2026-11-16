"""Evaluate the VLM engine on CROHME images (inverted to black-on-white)."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from eval_crohme import edit_distance, load_split  # noqa: E402
from app.engines.vlm import LlamaServer, VlmEngine  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", default="2019")
    ap.add_argument("--gt-max-len", type=int, default=5)
    ap.add_argument("--stride", type=int, default=1)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--port", type=int, default=8849)
    ap.add_argument("--jsonl", default=str(ROOT / "_research" / "eval_vlm.jsonl"))
    args = ap.parse_args()

    items = load_split(ROOT / "_research" / "data", args.year)
    if args.gt_max_len:
        items = [it for it in items if len(it[2]) <= args.gt_max_len]
    if args.stride > 1:
        items = items[:: args.stride]
    if args.limit:
        items = items[: args.limit]

    server = LlamaServer(
        exe=ROOT / "tools" / "llama" / "llama-server.exe",
        model=ROOT / "models" / "vlm" / "model-q4km.gguf",
        mmproj=ROOT / "models" / "vlm" / "mmproj-q8.gguf",
        port=args.port,
    )
    engine = VlmEngine(server)
    assert server.ensure_started(), "llama-server not available"

    rows = []
    t_all = time.perf_counter()
    for i, (img_id, path, gt) in enumerate(items):
        img = Image.open(path).convert("L")
        img = ImageOps.invert(img).convert("RGB")
        t0 = time.perf_counter()
        rec = engine.recognize_image(img)
        ms = (time.perf_counter() - t0) * 1000
        pred = rec.latex.split()
        ok = pred == gt
        rows.append(
            {
                "id": img_id,
                "gt": gt,
                "pred": pred,
                "latex": rec.latex,
                "ok": ok,
                "ms": round(ms, 1),
            }
        )
        if (i + 1) % 25 == 0:
            print(f"  {i + 1}/{len(items)}", flush=True)

    n = len(rows)
    exact = sum(r["ok"] for r in rows)
    one = sum(edit_distance(r["pred"], r["gt"]) <= 1 for r in rows)
    cer = sum(edit_distance(r["pred"], r["gt"]) / max(1, len(r["gt"])) for r in rows) / n
    ms = [r["ms"] for r in rows]
    print(
        json.dumps(
            {
                "engine": "vlm",
                "n": n,
                "exp_rate": round(100 * exact / n, 2),
                "one_off_rate": round(100 * one / n, 2),
                "cer": round(100 * cer, 2),
                "p50_ms": round(statistics.median(ms), 1),
                "p95_ms": round(sorted(ms)[int(0.95 * (n - 1))], 1),
                "wall_s": round(time.perf_counter() - t_all, 1),
            },
            ensure_ascii=False,
        )
    )
    Path(args.jsonl).write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
