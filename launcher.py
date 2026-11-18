"""MathInk desktop launcher: tray icon + in-process server + clean shutdown.

Run with pythonw.exe (no console) from start.ps1. The FastAPI app runs in a
background thread; llama-server is a child process placed in a Windows job
object so it cannot survive this process. The tray menu can open the UI, copy
the tablet URL, release VRAM, open logs and fully quit.
"""

from __future__ import annotations

import logging
import ctypes
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(os.environ.get("MATHINK_ROOT", "")).resolve() if os.environ.get("MATHINK_ROOT") else None
if ROOT is None:
    if getattr(sys, "frozen", False):
        ROOT = Path(sys.executable).resolve().parent
    else:
        ROOT = Path(__file__).resolve().parent
os.environ.setdefault("MATHINK_ROOT", str(ROOT))
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "launcher.log"
PID_FILE = LOG_DIR / "launcher.pid"

sys.path.insert(0, str(ROOT / "backend"))

PORT = int(os.environ.get("MATHINK_PORT", "8848"))
HOST_URL = f"http://127.0.0.1:{PORT}"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

if sys.stdout is None:
    sys.stdout = open(LOG_FILE, "a", encoding="utf-8", buffering=1)
if sys.stderr is None:
    sys.stderr = sys.stdout

logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    encoding="utf-8",
)
log = logging.getLogger("mathink.launcher")


def port_open() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1", PORT)) == 0


_mutex_handle = None


def acquire_single_instance() -> bool:
    """Named mutex so two start.ps1 invocations cannot race."""
    global _mutex_handle
    if os.name != "nt":
        return True
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.CreateMutexW(None, False, "Global\\MathInkTrayLauncher")
    if not handle:
        return True
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        kernel32.CloseHandle(handle)
        return False
    _mutex_handle = handle
    return True


def _ps(script: str) -> str:
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=CREATE_NO_WINDOW,
        )
        return out.stdout.strip()
    except Exception:
        log.debug("powershell failed", exc_info=True)
        return ""


def kill_stale_llama() -> int:
    """Kill llama-server processes that belong to this project."""
    if os.name != "nt":
        return 0
    script = (
        "Get-CimInstance Win32_Process -Filter \"Name='llama-server.exe'\" | "
        "Where-Object { $_.CommandLine -like '*mathink*' } | "
        "ForEach-Object { $_.ProcessId }"
    )
    killed = 0
    for token in _ps(script).split():
        try:
            pid = int(token)
        except ValueError:
            continue
        log.warning("killing stale llama-server pid=%s", pid)
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/F", "/T"],
            capture_output=True,
            creationflags=CREATE_NO_WINDOW,
        )
        killed += 1
    return killed


def lan_ip() -> str:
    try:
        from app.main import _lan_ip_address

        return _lan_ip_address()
    except Exception:
        return "127.0.0.1"


def make_icon():
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, 63, 63], radius=14, fill=(79, 70, 229, 255))
    # stylized integral sign
    d.line(
        [(42, 12), (33, 17), (30, 27), (32, 38), (28, 48), (18, 52)],
        fill="white",
        width=5,
        joint="curve",
    )
    return img


class Launcher:
    def __init__(self) -> None:
        self.server = None
        self.thread: threading.Thread | None = None
        self.icon = None
        self.status = "启动中…"
        self._quitting = False

    # ---------------------------------------------------------------- server

    def start_server(self) -> bool:
        import uvicorn

        config = uvicorn.Config(
            "app.main:app",
            host="0.0.0.0",
            port=PORT,
            log_level="info",
            log_config=None,
            access_log=False,
        )
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, name="uvicorn", daemon=True)
        self.thread.start()
        for _ in range(200):
            if getattr(self.server, "started", False):
                self.status = f"运行中 · {HOST_URL}"
                log.info("server started on %s", HOST_URL)
                return True
            if not self.thread.is_alive():
                break
            time.sleep(0.1)
        self.status = "启动失败"
        log.error("server failed to start (port %s)", PORT)
        return False

    def stop_server(self) -> None:
        if self.server is not None:
            self.server.should_exit = True
        if self.thread is not None:
            self.thread.join(timeout=15)
        try:
            import app.main as m

            if getattr(m, "vlm_server", None) is not None:
                m.vlm_server.stop()
        except Exception:
            log.debug("vlm stop failed", exc_info=True)
        kill_stale_llama()
        self.server = None
        self.thread = None

    # ---------------------------------------------------------------- actions

    def open_host(self, *_) -> None:
        webbrowser.open(HOST_URL)

    def copy_pad(self, *_) -> None:
        url = f"http://{lan_ip()}:{PORT}/pad"
        try:
            subprocess.run("clip", input=url, text=True, shell=True, check=False)
            self.status = "平板地址已复制"
        except Exception:
            log.warning("clipboard failed", exc_info=True)

    def release_vram(self, *_) -> None:
        threading.Thread(target=self._release_vram, daemon=True).start()

    def _release_vram(self) -> None:
        try:
            import app.main as m

            if getattr(m, "vlm_server", None) is not None:
                m.vlm_server.stop()
            self.status = "显存已释放（下次识别自动加载）"
            log.info("VRAM released by tray action")
        except Exception as exc:
            self.status = f"释放失败：{exc}"
            log.warning("release VRAM failed", exc_info=True)

    def open_log(self, *_) -> None:
        try:
            os.startfile(LOG_FILE)  # type: ignore[attr-defined]
        except Exception:
            log.warning("open log failed", exc_info=True)

    def quit(self, *_) -> None:
        if self._quitting:
            return
        self._quitting = True
        self.status = "正在退出…"
        log.info("quit requested")
        try:
            if self.icon is not None:
                self.icon.title = "MathInk · 正在退出"
        except Exception:
            pass
        self.stop_server()
        try:
            PID_FILE.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            if self.icon is not None:
                self.icon.stop()
        except Exception:
            pass
        log.info("bye")
        time.sleep(0.2)
        os._exit(0)

    # ---------------------------------------------------------------- tray

    def run_tray(self) -> None:
        import pystray

        menu = pystray.Menu(
            pystray.MenuItem("打开主机端", self.open_host, default=True),
            pystray.MenuItem("复制平板地址", self.copy_pad),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(lambda item: f"状态：{self.status}", None, enabled=False),
            pystray.MenuItem("释放显存（下次识别重载）", self.release_vram),
            pystray.MenuItem("打开日志", self.open_log),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出 MathInk（彻底关闭）", self.quit),
        )
        self.icon = pystray.Icon("MathInk", make_icon(), "MathInk 手写公式", menu)
        threading.Thread(target=self._log_tray_state, daemon=True).start()
        try:
            self.icon.run()
        except KeyboardInterrupt:
            self.quit()
        except Exception:
            log.exception("tray failed")
            self.quit()

    def _log_tray_state(self) -> None:
        time.sleep(2.0)
        try:
            log.info("tray icon visible=%s", getattr(self.icon, "visible", None))
        except Exception:
            pass


def force_stop() -> None:
    """CLI path for stop.ps1: kill the launcher tree, then stale children."""
    killed = 0
    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/F", "/T"],
            capture_output=True,
            creationflags=CREATE_NO_WINDOW,
        )
        killed += 1
    except Exception:
        pass
    killed += kill_stale_llama()
    try:
        PID_FILE.unlink(missing_ok=True)
    except OSError:
        pass
    print(f"stopped ({killed} target(s))")


def main() -> None:
    if "--stop" in sys.argv:
        force_stop()
        return

    if "--selftest-quit" in sys.argv:
        app = Launcher()
        if not app.start_server():
            print("server failed")
            return
        time.sleep(6)
        print(f"VRAM check then quit; status={app.status}")
        app.quit()
        return

    if not acquire_single_instance():
        log.info("another launcher instance already holds the mutex")
        webbrowser.open(HOST_URL)
        print(f"MathInk already running: {HOST_URL}")
        return

    if port_open():
        log.info("another instance is already listening on %s", PORT)
        webbrowser.open(HOST_URL)
        print(f"MathInk already running: {HOST_URL}")
        return

    kill_stale_llama()
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    log.info("launcher pid=%s port=%s", os.getpid(), PORT)

    app = Launcher()
    if not app.start_server():
        # keep tray visible so the user can open the log / quit
        app.run_tray()
        return
    app.run_tray()


if __name__ == "__main__":
    main()
