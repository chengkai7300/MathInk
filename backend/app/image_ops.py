"""Canvas stroke preprocessing for CoMER.

Faithful port of the reference pipeline in `ink-on` (Apache-2.0):
white strokes on black, content scaled to height 128, width aligned to 64,
top-left aligned, with a padding mask.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np
from PIL import Image, ImageDraw

MODEL_H = 256
TARGET_H = 128
MAX_W = 1024
MIN_W = 128
W_ALIGN = 64
PAD = 16
RESAMPLE_INTERVAL = 3.0
SUPERSAMPLE = 2  # render 2x then downscale for smoother strokes


@dataclass
class Point:
    x: float
    y: float


@dataclass
class Stroke:
    points: list[Point]
    width: float = 3.0


def resample_points(points: Sequence[Point], interval: float = RESAMPLE_INTERVAL) -> list[Point]:
    if len(points) < 2:
        return list(points)
    out: list[Point] = [points[0]]
    remaining = interval
    for i in range(1, len(points)):
        prev, curr = points[i - 1], points[i]
        dx, dy = curr.x - prev.x, curr.y - prev.y
        dist = math.hypot(dx, dy)
        if dist <= remaining:
            remaining -= dist
            continue
        covered = remaining
        while covered <= dist:
            t = covered / dist
            out.append(Point(prev.x + dx * t, prev.y + dy * t))
            covered += interval
        remaining = covered - dist
    out.append(points[-1])
    return out


def _bbox(strokes: Sequence[Stroke]) -> tuple[float, float, float, float]:
    min_x = min_y = math.inf
    max_x = max_y = -math.inf
    for s in strokes:
        for p in s.points:
            min_x = min(min_x, p.x)
            min_y = min(min_y, p.y)
            max_x = max(max_x, p.x)
            max_y = max(max_y, p.y)
    return min_x, min_y, max_x, max_y


def is_meaningful(strokes: Sequence[Stroke]) -> bool:
    if not strokes:
        return False
    min_x, min_y, max_x, max_y = _bbox(strokes)
    if max_x - min_x < 8 and max_y - min_y < 8:
        return False
    total_points = sum(len(s.points) for s in strokes)
    total_len = 0.0
    for s in strokes:
        for i in range(1, len(s.points)):
            total_len += math.hypot(
                s.points[i].x - s.points[i - 1].x, s.points[i].y - s.points[i - 1].y
            )
    return total_points >= 6 and total_len >= 15


def _quadratic(p0: Point, c: Point, p1: Point, steps: int) -> list[Point]:
    pts = []
    for i in range(1, steps + 1):
        t = i / steps
        mt = 1 - t
        x = mt * mt * p0.x + 2 * mt * t * c.x + t * t * p1.x
        y = mt * mt * p0.y + 2 * mt * t * c.y + t * t * p1.y
        pts.append(Point(x, y))
    return pts


def render_strokes(strokes: Sequence[Stroke], supersample: int = SUPERSAMPLE) -> Image.Image:
    """White strokes on black background, padded by PAD on all sides."""
    min_x, min_y, max_x, max_y = _bbox(strokes)
    raw_w = max(1, math.ceil(max_x - min_x))
    raw_h = max(1, math.ceil(max_y - min_y))
    ss = max(1, supersample)
    img = Image.new("L", ((raw_w + PAD * 2) * ss, (raw_h + PAD * 2) * ss), 0)
    draw = ImageDraw.Draw(img)
    ox = (PAD - min_x) * ss
    oy = (PAD - min_y) * ss

    for stroke in strokes:
        if not stroke.points:
            continue
        pts = resample_points(stroke.points)
        width = max(2.0, stroke.width) * ss
        r = width / 2.0
        if len(pts) == 1:
            px, py = pts[0].x * ss + ox, pts[0].y * ss + oy
            draw.ellipse([px - r, py - r, px + r, py + r], fill=255)
            continue
        if len(pts) == 2:
            poly = [Point(p.x * ss + ox, p.y * ss + oy) for p in pts]
        else:
            poly = [Point(pts[0].x * ss + ox, pts[0].y * ss + oy)]
            for i in range(1, len(pts) - 1):
                p0 = pts[i - 1]
                c = pts[i]
                p1 = Point((pts[i].x + pts[i + 1].x) / 2, (pts[i].y + pts[i + 1].y) / 2)
                steps = max(3, int(math.hypot(c.x - p0.x, c.y - p0.y) / 2) + 1)
                for q in _quadratic(p0, c, p1, steps):
                    poly.append(Point(q.x * ss + ox, q.y * ss + oy))
            last = pts[-1]
            poly.append(Point(last.x * ss + ox, last.y * ss + oy))

        draw.line([(p.x, p.y) for p in poly], fill=255, width=max(1, round(width)), joint="curve")
        for p in (poly[0], poly[-1]):
            draw.ellipse([p.x - r, p.y - r, p.x + r, p.y + r], fill=255)

    if ss > 1:
        img = img.resize((raw_w + PAD * 2, raw_h + PAD * 2), Image.LANCZOS)
    return img


def to_model_input(img: Image.Image) -> tuple[np.ndarray, np.ndarray]:
    """Match CoMER training preprocessing.

    Content keeps its natural size; it is only rescaled when outside the
    official limits (h: 16..256, w: 16..1024). The image is then placed
    top-left on a black 256-high canvas, width padded to a multiple of 64.
    """
    w, h = img.size
    scale = 1.0
    if h > MODEL_H or w > MAX_W:
        scale = min(MODEL_H / h, MAX_W / w)
    elif h < 16 or w < 16:
        scale = max(16 / h, 16 / w)
    if scale != 1.0:
        img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.BILINEAR)

    dw, dh = img.size
    canvas_w = max(64, min(MAX_W, math.ceil(dw / W_ALIGN) * W_ALIGN))
    canvas = Image.new("L", (canvas_w, MODEL_H), 0)
    canvas.paste(img, (0, 0))

    tensor = np.asarray(canvas, dtype=np.float32) / 255.0
    tensor = tensor[None, None, :, :]

    mask = np.ones((MODEL_H, canvas_w), dtype=bool)
    mask[:dh, :dw] = False
    mask = mask[None, :, :]
    return tensor, mask


def strokes_to_input(strokes: Sequence[Stroke]) -> tuple[np.ndarray, np.ndarray]:
    img = render_strokes(strokes)
    return to_model_input(img)


def image_to_input(img: Image.Image) -> tuple[np.ndarray, np.ndarray]:
    """Approximate preprocessing for uploaded/bitmap formulas."""
    g = img.convert("L")
    arr = np.asarray(g)
    if arr.mean() > 127:
        g = Image.fromarray(255 - arr)
    # crop to ink
    ys, xs = np.where(arr > 40)
    if len(xs):
        g = g.crop((int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1))
    padded = Image.new("L", (g.width + PAD * 2, g.height + PAD * 2), 0)
    padded.paste(g, (PAD, PAD))
    return to_model_input(padded)


def strokes_to_vlm_image(
    strokes: Sequence[Stroke],
    max_side: int = 512,
    pad: int = 24,
    line_width: float = 4.0,
    target_height: int = 160,
) -> Image.Image:
    """Render a natural black-on-white formula image for a vision-language model.

    Small writing is scaled up to ~target_height so the model sees CROHME-like
    proportions; large writing is capped at max_side.
    """
    min_x, min_y, max_x, max_y = _bbox(strokes)
    raw_w = max(1, math.ceil(max_x - min_x))
    raw_h = max(1, math.ceil(max_y - min_y))
    ss = 2
    w = (raw_w + pad * 2) * ss
    h = (raw_h + pad * 2) * ss
    img = Image.new("L", (w, h), 255)
    draw = ImageDraw.Draw(img)
    ox = (pad - min_x) * ss
    oy = (pad - min_y) * ss

    for stroke in strokes:
        if not stroke.points:
            continue
        pts = resample_points(stroke.points)
        width = max(2.0, line_width) * ss
        r = width / 2.0
        if len(pts) == 1:
            px, py = pts[0].x * ss + ox, pts[0].y * ss + oy
            draw.ellipse([px - r, py - r, px + r, py + r], fill=0)
            continue
        if len(pts) == 2:
            poly = [Point(p.x * ss + ox, p.y * ss + oy) for p in pts]
        else:
            poly = [Point(pts[0].x * ss + ox, pts[0].y * ss + oy)]
            for i in range(1, len(pts) - 1):
                p0, c = pts[i - 1], pts[i]
                p1 = Point((pts[i].x + pts[i + 1].x) / 2, (pts[i].y + pts[i + 1].y) / 2)
                steps = max(3, int(math.hypot(c.x - p0.x, c.y - p0.y) / 2) + 1)
                for q in _quadratic(p0, c, p1, steps):
                    poly.append(Point(q.x * ss + ox, q.y * ss + oy))
            last = pts[-1]
            poly.append(Point(last.x * ss + ox, last.y * ss + oy))
        draw.line([(p.x, p.y) for p in poly], fill=0, width=max(1, round(width)), joint="curve")
        for p in (poly[0], poly[-1]):
            draw.ellipse([p.x - r, p.y - r, p.x + r, p.y + r], fill=0)

    img = img.resize((raw_w + pad * 2, raw_h + pad * 2), Image.LANCZOS)

    # scale to a friendly size
    scale = 1.0
    if img.height < target_height:
        scale = target_height / max(1, img.height)
        scale = min(scale, max_side / max(img.width, img.height))
    if max(img.width, img.height) * scale > max_side:
        scale = max_side / max(img.width, img.height)
    if scale != 1.0:
        img = img.resize(
            (max(1, round(img.width * scale)), max(1, round(img.height * scale))),
            Image.LANCZOS,
        )
    return img.convert("RGB")
