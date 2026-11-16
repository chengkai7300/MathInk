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
    },
    "vlm": {
        "dir": ROOT / "models" / "vlm",
        "files": {
            "model-q4km.gguf": "https://hf-mirror.com/mradermacher/Uni-MuMER-Qwen3-VL-2B-GGUF/resolve/main/Uni-MuMER-Qwen3-VL-2B.Q4_K_M.gguf",
            "mmproj-q8.gguf": "https://hf-mirror.com/mradermacher/Uni-MuMER-Qwen3-VL-2B-GGUF/resolve/main/Uni-MuMER-Qwen3-VL-2B.mmproj-Q8_0.gguf",
        },
        "size_mb": 1550,
        "license": "Apache-2.0 (Uni-MuMER, Qwen3-VL base)",
    },
}

LLAMA_URL = "https://github.com/ggml-org/llama.cpp/releases/download/b12359/llama-b12359-bin-win-vulkan-x64.zip"
LLAMA_DIR = ROOT / "tools" / "llama"


def setup_llama(force: bool = False) -> None:
    if (LLAMA_DIR / "llama-server.exe").exists() and not force:
        print(f"llama.cpp: exists ({LLAMA_DIR})")
        return
    import tempfile
    import zipfile

    tmp = Path(tempfile.gettempdir()) / "llama-vulkan.zip"
    print(f"llama.cpp: downloading {LLAMA_URL}")
    download(LLAMA_URL, tmp)
    LLAMA_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(tmp) as zf:
        zf.extractall(LLAMA_DIR)
    tmp.unlink(missing_ok=True)
    print(f"llama.cpp: extracted to {LLAMA_DIR}")


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
    ap.add_argument("--llama", action="store_true", help="also download llama.cpp runtime")
    args = ap.parse_args()

    if args.list:
        for name, spec in MODELS.items():
            print(f"{name:10s} {spec['size_mb']:>6} MB  {spec['license']}")
        print(f"{'llama.cpp':10s} {38:>6} MB  MIT (binaries)")
        return

    if args.llama:
        setup_llama(args.force)

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
