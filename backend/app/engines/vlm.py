"""VLM engine: Uni-MuMER 2B (Qwen3-VL) served by llama.cpp.

The server is started lazily on the first request and kept alive; the model is
a GGUF pair (language model + mmproj vision projector). Everything stays local.
"""

from __future__ import annotations

import base64
import ctypes
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

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _assign_kill_on_close_job(pid: int):
    """Put the child in a Windows job so it dies if this process dies.

    Returns the job handle (must stay open) or None on failure. This is what
    prevents an orphaned llama-server from keeping VRAM after a crash or a
    forced window close.
    """
    if os.name != "nt":
        return None
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", ctypes.c_uint32),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", ctypes.c_uint32),
                ("Affinity", ctypes.POINTER(ctypes.c_ulong)),
                ("PriorityClass", ctypes.c_uint32),
                ("SchedulingClass", ctypes.c_uint32),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = 0x00002000  # KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
            job, 9, ctypes.byref(info), ctypes.sizeof(info)
        ):
            kernel32.CloseHandle(job)
            return None
        handle = kernel32.OpenProcess(0x0100 | 0x0001, False, pid)  # SET_QUOTA|TERMINATE
        if not handle:
            kernel32.CloseHandle(job)
            return None
        ok = kernel32.AssignProcessToJobObject(job, handle)
        kernel32.CloseHandle(handle)
        if not ok:
            kernel32.CloseHandle(job)
            return None
        return job
    except Exception:
        LOG.debug("could not assign job object", exc_info=True)
        return None


def _taskkill(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/F", "/T"],
            capture_output=True,
            creationflags=CREATE_NO_WINDOW,
        )


def _is_llama_pid(pid: int) -> bool:
    """Check that a PID still belongs to llama-server.exe (avoid PID reuse)."""
    if os.name != "nt" or pid <= 0:
        return False
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        buf = ctypes.create_unicode_buffer(1024)
        size = ctypes.c_uint32(1024)
        ok = kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size))
        kernel32.CloseHandle(handle)
        return bool(ok) and buf.value.lower().endswith("llama-server.exe")
    except Exception:
        return False



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
        self._job = None
        base = log_path.parent if log_path else Path(".")
        self.pid_path = base / "llama-server.pid"

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
                    "2048",
                    "--parallel",
                    "1",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(self.port),
                    "--jinja",
                    "--no-warmup",
                ]
                LOG.info("starting llama-server: %s", " ".join(args))
                self.proc = subprocess.Popen(
                    args,
                    cwd=str(self.exe.parent),
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    creationflags=CREATE_NO_WINDOW,
                )
                self._last_start = time.time()
                try:
                    self.pid_path.parent.mkdir(parents=True, exist_ok=True)
                    self.pid_path.write_text(str(self.proc.pid), encoding="utf-8")
                except OSError:
                    pass
                self._job = _assign_kill_on_close_job(self.proc.pid)
                if self._job is None:
                    LOG.warning("job object unavailable; relying on explicit shutdown")

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

    def _close_job(self) -> None:
        if self._job is not None:
            try:
                ctypes.WinDLL("kernel32").CloseHandle(self._job)
            except Exception:
                pass
            self._job = None

    def _remove_pid(self) -> None:
        try:
            self.pid_path.unlink(missing_ok=True)
        except OSError:
            pass

    def stop(self) -> None:
        """Stop llama-server and make sure it is really gone (frees VRAM)."""
        proc = self.proc
        self.proc = None
        pid = proc.pid if proc is not None else None
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                pass
        if pid and _is_llama_pid(pid):
            LOG.warning("llama-server %s still alive; taskkill", pid)
            _taskkill(pid)
        if pid is None:
            try:
                stale = int(self.pid_path.read_text(encoding="utf-8").strip())
            except Exception:
                stale = None
            if stale and _is_llama_pid(stale):
                LOG.warning("killing stale llama-server %s", stale)
                _taskkill(stale)
        self._close_job()
        self._remove_pid()
        self._last_start = 0.0


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
