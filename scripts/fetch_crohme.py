"""Download CROHME test data used by the evaluation scripts.

The archive comes from the CoMER repository (research use only).
Extracts to `_research/data/{2014,2016,2019,train}`.
"""

from __future__ import annotations

import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "_research" / "data"
ZIP_PATH = ROOT / "_research" / "comer_data.zip"
URL = "https://github.com/Green-Wood/CoMER/raw/master/data.zip"


def main() -> None:
    if (DATA_DIR / "2019" / "caption.txt").exists():
        print(f"already present: {DATA_DIR}")
        return
    ZIP_PATH.parent.mkdir(parents=True, exist_ok=True)

    def hook(blocks: int, block_size: int, total: int) -> None:
        if total > 0:
            done = min(blocks * block_size, total)
            sys.stdout.write(f"\r  {done * 100 // total}% ({done >> 20}/{total >> 20} MB)")
            sys.stdout.flush()

    print(f"downloading {URL}")
    urllib.request.urlretrieve(URL, ZIP_PATH, reporthook=hook)
    print()
    with zipfile.ZipFile(ZIP_PATH) as zf:
        zf.extractall(ROOT / "_research")
    print(f"extracted to {DATA_DIR}")
    print("run: python scripts/eval_crohme.py --gt-max-len 5 --limit 300 --variants official")


if __name__ == "__main__":
    main()
