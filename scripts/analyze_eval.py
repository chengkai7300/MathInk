"""Summarize a per-item eval JSONL produced by eval_crohme.py --jsonl."""

from __future__ import annotations

import argparse
import json
import statistics


def edit_distance(a: list[str], b: list[str]) -> int:
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] != b[j - 1]))
        prev = cur
    return prev[-1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    args = ap.parse_args()

    rows = [json.loads(line) for line in open(args.path, encoding="utf-8") if line.strip()]
    n = len(rows)
    exact = sum(1 for r in rows if r["ok"])
    one = sum(1 for r in rows if edit_distance(r["pred"], r["gt"]) <= 1)
    cer = sum(edit_distance(r["pred"], r["gt"]) / max(1, len(r["gt"])) for r in rows) / n
    ms = [r["ms"] for r in rows]

    print(f"n={n}  exact={100*exact/n:.1f}%  <=1edit={100*one/n:.1f}%  CER={100*cer:.1f}%")
    print(f"p50={statistics.median(ms):.0f}ms  p95={sorted(ms)[int(0.95*(n-1))]:.0f}ms")

    print("\nby ground-truth length:")
    for name, lo, hi in [("1-5", 1, 5), ("6-10", 6, 10), ("11-15", 11, 15), ("16-25", 16, 25), ("26+", 26, 999)]:
        sub = [r for r in rows if lo <= len(r["gt"]) <= hi]
        if not sub:
            continue
        e = 100 * sum(1 for r in sub if r["ok"]) / len(sub)
        o = 100 * sum(1 for r in sub if edit_distance(r["pred"], r["gt"]) <= 1) / len(sub)
        print(f"  {name:6s} n={len(sub):3d}  exact={e:5.1f}%  <=1edit={o:5.1f}%")

    print("\nworst examples (short, wrong):")
    shown = 0
    for r in sorted(rows, key=lambda r: len(r["gt"])):
        if r["ok"] or len(r["gt"]) > 10:
            continue
        print("  gt  :", " ".join(r["gt"]))
        print("  pred:", " ".join(r["pred"]))
        shown += 1
        if shown >= 8:
            break


if __name__ == "__main__":
    main()
