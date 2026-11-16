"""Smoke tests: run with `.venv\\Scripts\\python.exe tests\\test_smoke.py`."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import latex_utils  # noqa: E402
from app.image_ops import Point, Stroke, is_meaningful, strokes_to_input  # noqa: E402


def test_repair_braces():
    assert latex_utils.repair(["{", "x"]) == ["{", "x", "}"]
    assert latex_utils.repair(["}", "x"]) == ["x"]


def test_repair_frac():
    # missing second argument is left alone (we do not invent content)
    assert latex_utils.repair(["\\frac", "{", "1", "}"]) == ["\\frac", "{", "1", "}"]
    # extra arguments are dropped
    out = latex_utils.repair(["\\frac", "{", "1", "}", "{", "2", "}", "{", "3", "}"])
    assert out == ["\\frac", "{", "1", "}", "{", "2", "}"]


def test_complete():
    assert latex_utils.is_complete(["x", "+", "1"])
    assert not latex_utils.is_complete(["\\frac", "{", "1", "}"])
    assert latex_utils.is_balanced(["\\frac", "{", "1", "}", "{", "2", "}"])


def test_normalize():
    assert latex_utils.normalize("\\left ( x \\right )") == "( x )"
    assert latex_utils.normalize("a   +   b") == "a + b"


def test_preprocess_shapes():
    strokes = [
        Stroke([Point(10, 10), Point(200, 10)], width=3),
        Stroke([Point(100, 40), Point(100, 160)], width=3),
    ]
    tensor, mask = strokes_to_input(strokes)
    assert tensor.shape == (1, 1, 256, 256)
    assert tensor.dtype == np.float32
    assert tensor.max() > 0.5
    assert mask.shape == (1, 256, 256)
    assert mask[0, 0, 0] == False  # content starts top-left
    assert mask[0, -1, -1] == True  # bottom-right is padding


def test_meaningful():
    assert not is_meaningful([])
    assert not is_meaningful([Stroke([Point(1, 1), Point(2, 2)])])
    line = [Point(x, x) for x in range(0, 60, 8)]
    assert is_meaningful([Stroke(line)])


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("ok", fn.__name__)
    print(f"{len(fns)} tests passed")
