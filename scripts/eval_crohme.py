"""Evaluate the CoMER ONNX engine on CROHME test data with several preprocessing variants."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.engines.comer import ComerEngine  # noqa: E402


def load_split(data_dir: Path, year: str):
    cap = data_dir / year / "caption.txt"
    items = []
    for line in cap.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split()
        if not parts:
            continue
        img_id, tokens = parts[0], parts[1:]
        img_path = data_dir / year / "img" / f"{img_id}.bmp"
        if img_path.exists():
            items.append((img_id, img_path, tokens))
    return items


def _crop(g: Image.Image) -> Image.Image:
    a = np.asarray(g)
    ys, xs = np.where(a > 40)
    if len(xs) == 0:
        return g
    return g.crop((int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1))


def prep(g: Image.Image, variant: str) -> tuple[np.ndarray, np.ndarray]:
    g = g.convert("L")
    if variant in ("inkon", "crop"):
        g = _crop(g)
    w, h = g.size
    if variant == "inkon":
        target_h = 128
        scale = min(target_h / h, 1024 / w)
        nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
    else:  # official / crop
        scale = 1.0
        if h > 256 or w > 1024:
            scale = min(256 / h, 1024 / w)
        elif h < 16 or w < 16:
            scale = max(16 / h, 16 / w)
        nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
    if (nw, nh) != (w, h):
        g = g.resize((nw, nh), Image.BILINEAR)

    cw = max(64, math.ceil(nw / 64) * 64)
    cw = min(cw, 1024)
    canvas = Image.new("L", (cw, 256), 0)
    canvas.paste(g, (0, 0))

    tensor = np.asarray(canvas, dtype=np.float32) / 255.0
    tensor = tensor[None, None, :, :]
    mask = np.ones((1, 256, cw), dtype=bool)
    mask[0, :nh, :nw] = False
    return tensor, mask


def edit_distance(a: list[str], b: list[str]) -> int:
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cur[j] = min(
                prev[j] + 1,
                cur[j - 1] + 1,
                prev[j - 1] + (a[i - 1] != b[j - 1]),
            )
        prev = cur
    return prev[-1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", default="2019")
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--stride", type=int, default=1, help="take every Nth sample")
    ap.add_argument("--beam", type=int, default=1)
    ap.add_argument("--steps", type=int, default=40)
    ap.add_argument("--variants", default="official,inkon,crop")
    ap.add_argument("--provider", default="cpu")
    ap.add_argument("--jsonl", default="", help="write per-item results here")
    ap.add_argument("--gt-max-len", type=int, default=0, help="only keep formulas with <= N tokens")
    args = ap.parse_args()

    data_dir = ROOT / "_research" / "data"
    items = load_split(data_dir, args.year)
    if args.gt_max_len:
        items = [it for it in items if len(it[2]) <= args.gt_max_len]
    if args.stride > 1:
        items = items[:: args.stride]
    if args.limit:
        items = items[: args.limit]

    engine = ComerEngine(
        ROOT / "models" / "comer",
        provider=args.provider,
        beam_width=args.beam,
        max_steps=args.steps,
    )

    report = {}
    for variant in args.variants.split(","):
        exact = 0
        cer_sum = 0.0
        times = []
        samples = []
        buckets = {"short": [0, 0], "medium": [0, 0], "long": [0, 0]}  # [exact, n]
        one_off = 0
        jf = open(args.jsonl, "a", encoding="utf-8") if args.jsonl else None
        for idx, (img_id, path, gt) in enumerate(items):
            g = Image.open(path)
            tensor, mask = prep(g, variant)
            t0 = time.perf_counter()
            rec = engine.recognize_tensor(tensor, mask)
            times.append((time.perf_counter() - t0) * 1000)
            pred = rec.tokens
            ok = pred == gt
            if ok:
                exact += 1
            dist = edit_distance(pred, gt)
            if dist <= 1:
                one_off += 1
            cer_sum += dist / max(1, len(gt))
            key = "short" if len(gt) <= 5 else "medium" if len(gt) <= 12 else "long"
            buckets[key][0] += int(ok)
            buckets[key][1] += 1
            if len(samples) < 8:
                samples.append({"id": img_id, "gt": " ".join(gt), "pred": " ".join(pred)})
            if (idx + 1) % 50 == 0:
                print(f"  {variant}: {idx + 1}/{len(items)}", flush=True)
            if jf:
                jf.write(
                    json.dumps(
                        {
                            "variant": variant,
                            "id": img_id,
                            "gt": gt,
                            "pred": pred,
                            "ok": ok,
                            "ms": round(times[-1], 1),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                jf.flush()
        if jf:
            jf.close()
        n = len(items)
        report[variant] = {
            "n": n,
            "exp_rate": round(100 * exact / n, 2),
            "one_off_rate": round(100 * one_off / n, 2),
            "cer": round(100 * cer_sum / n, 2),
            "exp_by_len": {
                k: (round(100 * v[0] / v[1], 1) if v[1] else None)
                for k, v in buckets.items()
            },
            "n_by_len": {k: v[1] for k, v in buckets.items()},
            "p50_ms": round(statistics.median(times), 1),
            "p95_ms": round(sorted(times)[int(0.95 * (n - 1))], 1),
            "samples": samples,
        }
        print(variant, json.dumps({k: v for k, v in report[variant].items() if k != "samples"}))

    out = ROOT / "_research" / f"eval_comer_{args.year}_beam{args.beam}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("saved", out)


if __name__ == "__main__":
    main()
