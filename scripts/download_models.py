"""Download local model files for MathInk.

Usage:
    python scripts/download_models.py --engine comer
    python scripts/download_models.py --list
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

MODELS = {
    "comer": {
        "dir": ROOT / "models" / "comer",
        "files": {
            "encoder_int8.onnx": "https://github.com/kimseungdae/ink-on/releases/download/v0.1.0/encoder_int8.onnx",
            "decoder_int8.onnx": "https://github.com/kimseungdae/ink-on/releases/download/v0.1.0/decoder_int8.onnx",
            "vocab.json": "https://github.com/kimseungdae/ink-on/releases/download/v0.1.0/vocab.json",
        },
        "size_mb": 7.2,
        "license": "Apache-2.0 (packaged by ink-on; CoMER weights from CROHME)",
    }
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")

    def hook(blocks: int, block_size: int, total: int) -> None:
        if total > 0:
            done = min(blocks * block_size, total)
            pct = done * 100 // total
            sys.stdout.write(f"\r  {dest.name}: {pct}% ({done >> 20}/{total >> 20} MB)")
            sys.stdout.flush()

    urllib.request.urlretrieve(url, tmp, reporthook=hook)
    sys.stdout.write("\n")
    tmp.replace(dest)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", choices=sorted(MODELS), default="comer")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    if args.list:
        for name, spec in MODELS.items():
            print(f"{name:10s} {spec['size_mb']:>6} MB  {spec['license']}")
        return

    spec = MODELS[args.engine]
    print(f"engine: {args.engine} -> {spec['dir']}")
    for filename, url in spec["files"].items():
        dest = spec["dir"] / filename
        if dest.exists() and not args.force:
            print(f"  {filename}: exists ({dest.stat().st_size} bytes)")
            continue
        print(f"  {filename}: downloading")
        download(url, dest)
    print("done")
    for filename in spec["files"]:
        p = spec["dir"] / filename
        print(f"  {filename:20s} {p.stat().st_size:>10} bytes  sha256={sha256(p)[:16]}…")


if __name__ == "__main__":
    main()
