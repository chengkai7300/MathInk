"""VLM engine: Uni-MuMER 2B (Qwen3-VL) served by llama.cpp.

The server is started lazily on the first request and kept alive; the model is
a GGUF pair (language model + mmproj vision projector). Everything stays local.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Sequence

from .. import image_ops, latex_utils
from .base import Recognition

LOG = logging.getLogger("mathink.vlm")

PROMPT = "Please write the LaTeX code of the formula in the image."
SYSTEM = "You are a helpful assistant."


def clean_latex(text: str) -> str:
    s = (text or "").strip()
    if not s:
        return ""
    # strip markdown code fences
    if "```" in s:
        parts = s.split("```")
        for part in parts:
            p = part.strip()
            if p.lower().startswith("latex"):
                p = p[5:].strip()
            if p:
                s = p
                break
    # drop common prose prefixes
    for prefix in ("LaTeX:", "LaTeX：", "The LaTeX code is", "The formula is"):
        if s.lower().startswith(prefix.lower()):
            s = s[len(prefix) :].strip()
    # if multiple lines, keep the most math-like one
    lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
    if len(lines) > 1:
        def score(ln: str) -> int:
            return sum(ln.count(ch) for ch in "\\^_{}()[]") + (2 if "\\" in ln else 0)

        s = max(lines, key=score)
    s = s.strip().strip("$").strip()
    if s.startswith("\\[") and s.endswith("\\]"):
        s = s[2:-2].strip()
    if s.startswith("\\(") and s.endswith("\\)"):
        s = s[2:-2].strip()
    s = s.rstrip("。.")
    return " ".join(s.split())


class LlamaServer:
    """Manages a local llama-server process with a vision projector."""

    def __init__(
        self,
        exe: Path,
        model: Path,
        mmproj: Path,
        port: int = 8849,
        log_path: Path | None = None,
        threads: int = 8,
    ):
        self.exe = Path(exe)
        self.model = Path(model)
        self.mmproj = Path(mmproj)
        self.port = port
        self.log_path = log_path
        self.threads = threads
        self.proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._last_start = 0.0

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def files_ready(self) -> bool:
        return self.exe.exists() and self.model.exists() and self.mmproj.exists()

    def healthy(self, timeout: float = 1.5) -> bool:
        try:
            with urllib.request.urlopen(f"{self.base_url}/health", timeout=timeout) as r:
                return r.status == 200
        except Exception:
            return False

    def ensure_started(self, timeout: float = 240.0) -> bool:
        if self.healthy():
            return True
        if not self.files_ready():
            LOG.warning("VLM files missing: exe=%s model=%s mmproj=%s", self.exe, self.model, self.mmproj)
            return False

        with self._lock:
            if self.healthy():
                return True
            if self.proc is not None and self.proc.poll() is None:
                # someone else is starting it; wait below
                pass
            else:
                self.log_path.parent.mkdir(parents=True, exist_ok=True) if self.log_path else None
                log = (
                    open(self.log_path, "ab", buffering=0)
                    if self.log_path
                    else subprocess.DEVNULL
                )
                args = [
                    str(self.exe),
                    "-m",
                    str(self.model),
                    "--mmproj",
                    str(self.mmproj),
                    "-ngl",
                    "99",
                    "-c",
                    "4096",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(self.port),
                    "-np",
                    "1",
                    "--jinja",
                    "--no-warmup",
                ]
                LOG.info("starting llama-server: %s", " ".join(args))
                self.proc = subprocess.Popen(
                    args,
                    cwd=str(self.exe.parent),
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                self._last_start = time.time()

            deadline = time.time() + timeout
            while time.time() < deadline:
                if self.healthy(2.0):
                    LOG.info("llama-server ready in %.1fs", time.time() - self._last_start)
                    return True
                if self.proc is not None and self.proc.poll() is not None:
                    LOG.error("llama-server exited with %s", self.proc.returncode)
                    return False
                time.sleep(0.6)
            LOG.error("llama-server did not become healthy within %.0fs", timeout)
            return False

    def stop(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()


class VlmEngine:
    name = "vlm"

    def __init__(self, server: LlamaServer, timeout: float = 120.0):
        self.server = server
        self.timeout = timeout

    def available(self) -> bool:
        return self.server.files_ready()

    def warmup(self) -> bool:
        """Start the server and run one throwaway request (shader/graph warmup)."""
        if not self.server.ensure_started():
            return False
        try:
            strokes = [
                image_ops.Stroke(
                    points=[
                        image_ops.Point(20, 20),
                        image_ops.Point(80, 20),
                        image_ops.Point(80, 70),
                        image_ops.Point(20, 70),
                    ],
                    width=3,
                )
            ]
            self.recognize_strokes(strokes)
            return True
        except Exception as exc:  # pragma: no cover - warmup only
            LOG.warning("VLM warmup failed: %s", exc)
            return False

    def recognize_strokes(self, strokes: Sequence[image_ops.Stroke]) -> Recognition:
        t0 = time.perf_counter()
        img = image_ops.strokes_to_vlm_image(strokes)
        return self._recognize_pil(img, t0)

    def recognize_image(self, img) -> Recognition:
        t0 = time.perf_counter()
        if img.mode != "RGB":
            img = img.convert("RGB")
        return self._recognize_pil(img, t0)

    def _recognize_pil(self, img, t0: float) -> Recognition:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        t1 = time.perf_counter()

        if not self.server.ensure_started():
            raise RuntimeError("VLM server is not available")

        payload = {
            "model": "unimumer",
            "messages": [
                {"role": "system", "content": SYSTEM},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{b64}"},
                        },
                    ],
                },
            ],
            "max_tokens": 256,
            "temperature": 0.0,
            "top_p": 0.8,
            "stop": ["<|im_end|>", "<|endoftext|>"],
            "chat_template_kwargs": {"enable_thinking": False},
        }
        req = urllib.request.Request(
            f"{self.server.base_url}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        t2 = time.perf_counter()

        text = data["choices"][0]["message"]["content"]
        latex = latex_utils.normalize(clean_latex(text))
        tokens = latex.split()
        return Recognition(
            latex=latex,
            tokens=tokens,
            logprob=0.0,
            timings={
                "render_ms": round((t1 - t0) * 1000, 1),
                "vlm_ms": round((t2 - t1) * 1000, 1),
                "total_ms": round((t2 - t0) * 1000, 1),
            },
            engine=self.name,
        )
