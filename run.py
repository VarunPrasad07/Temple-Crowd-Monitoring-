#!/usr/bin/env python3
"""
Temple Crowd Dashboard - Unified Launcher
==========================================
Single file that starts BOTH the PHP web server AND the Python AI tracker.

Usage (from the project root folder):
    python run.py                              # Default: opens browser, tracker in --watch mode
    python run.py --port 8000                  # Choose PHP port
    python run.py --no-browser                 # Do not open the browser automatically
    python run.py --headless                   # Run tracker without OpenCV windows
    python run.py --php-only                   # Start PHP server only (no AI tracker)
    python run.py --ai-only                    # Start AI tracker only (PHP already running)

How it works
------------
1. Starts  `php -S 127.0.0.1:<port>`  in a background thread (the web + API server).
2. Starts  `python tracker/yolo_counter.py --watch`  as a subprocess.
   --watch mode polls api/devices.php every few seconds and automatically starts or stops
   a YOLO+ByteTrack counting thread for every camera that has "AI counting" switched on.
3. Opens the dashboard URL in your default browser.

Clicking the AI button (purple icon) in the Gate Monitoring table now works
immediately - the tracker picks up the change within seconds and starts counting.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT           = Path(__file__).parent.resolve()
TRACKER_SCRIPT = ROOT / "tracker" / "yolo_counter.py"
YOLO_MODEL     = ROOT / "yolov8n.pt"


def _print(tag: str, msg: str) -> None:
    print(f"[{tag}] {msg}", flush=True)


def _php_binary() -> str:
    for candidate in ("php", "php8", "php83", "php8.3"):
        try:
            subprocess.run([candidate, "-r", "echo 1;"], capture_output=True, check=True, timeout=3)
            return candidate
        except Exception:
            continue
    raise RuntimeError(
        "PHP not found on PATH.\n"
        "Install PHP 8+ and make sure 'php' is on your PATH, then re-run this script."
    )


class PhpServer(threading.Thread):
    """Runs  php -S host:port  in the project root directory."""

    def __init__(self, host: str, port: int) -> None:
        super().__init__(daemon=True, name="php-server")
        self.host   = host
        self.port   = port
        self._proc  = None
        self._ready = threading.Event()
        self.url    = f"http://{host}:{port}"

    def run(self) -> None:
        php = _php_binary()
        cmd = [php, "-S", f"{self.host}:{self.port}"]
        _print("PHP", f"Starting server: {' '.join(cmd)}")
        try:
            self._proc = subprocess.Popen(
                cmd, cwd=str(ROOT),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
            )
            threading.Timer(1.2, self._ready.set).start()
            for line in self._proc.stdout:
                line = line.rstrip()
                if line:
                    _print("PHP", line)
        except FileNotFoundError as exc:
            _print("PHP", f"ERROR: {exc}")
        finally:
            self._ready.set()

    def wait_ready(self, timeout: float = 10.0) -> None:
        self._ready.wait(timeout)

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()


class AiTracker:
    """Runs  python tracker/yolo_counter.py --watch  in a subprocess."""

    def __init__(self, args: argparse.Namespace, api_url: str) -> None:
        self.args    = args
        self.api_url = api_url
        self._proc   = None

    def _build_cmd(self) -> list:
        model = str(YOLO_MODEL) if YOLO_MODEL.exists() else "yolov8n.pt"
        cmd = [
            sys.executable, str(TRACKER_SCRIPT),
            "--watch",
            "--api-url",        self.api_url,
            "--model",          model,
            "--preview-port",   str(self.args.preview_port),
            "--preview-host",   self.args.preview_host,
            "--watch-interval", str(self.args.watch_interval),
        ]
        if self.args.headless:
            cmd.append("--headless")
        if self.args.watch_all:
            cmd.append("--watch-all")
        return cmd

    def start(self) -> None:
        cmd = self._build_cmd()
        _print("AI", "Starting tracker in --watch mode (responds to AI button clicks in the UI)")
        self._proc = subprocess.Popen(cmd, cwd=str(ROOT))

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            _print("AI", "Stopping tracker ...")
            self._proc.terminate()
            try:
                self._proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self._proc.kill()

    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None


BANNER = """
+--------------------------------------------------------------+
|      Temple Crowd Monitoring Dashboard  -  Launcher          |
|                                                              |
|  PHP web server  +  Python AI (YOLO) tracker  combined       |
|  Click the AI button in Gate Monitoring to start real-time   |
|  YOLOv8 people counting for any camera, instantly.           |
+--------------------------------------------------------------+
"""


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Temple Crowd Dashboard - unified PHP + Python AI launcher",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--host",             default="127.0.0.1")
    ap.add_argument("--port",             type=int, default=8000)
    ap.add_argument("--preview-port",     type=int, default=8090)
    ap.add_argument("--preview-host",     default="127.0.0.1")
    ap.add_argument("--watch-interval",   type=int, default=5,
                    help="Seconds between AI-enable polls (lower = faster UI response)")
    ap.add_argument("--watch-all",        action="store_true")
    ap.add_argument("--headless",         action="store_true")
    ap.add_argument("--no-browser",       action="store_true")
    ap.add_argument("--php-only",         action="store_true")
    ap.add_argument("--ai-only",          action="store_true")
    return ap.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    print(BANNER)

    api_url       = f"http://{args.host}:{args.port}/api/device_reading.php"
    dashboard_url = f"http://{args.host}:{args.port}"

    php_server = None
    ai_tracker = None

    # -- Start PHP ---------------------------------------------------------
    if not args.ai_only:
        php_server = PhpServer(args.host, args.port)
        php_server.start()
        _print("Launcher", "Waiting for PHP server to initialise ...")
        php_server.wait_ready(timeout=8.0)
        _print("Launcher", f"Dashboard available at  {dashboard_url}")

    # -- Open browser ------------------------------------------------------
    if not args.no_browser and not args.ai_only:
        time.sleep(0.5)
        webbrowser.open(dashboard_url)
        _print("Launcher", f"Browser opened: {dashboard_url}")

    # -- Start AI tracker --------------------------------------------------
    if not args.php_only:
        if not TRACKER_SCRIPT.exists():
            _print("AI", f"WARNING: {TRACKER_SCRIPT} not found. Skipping AI tracker.")
        else:
            ai_tracker = AiTracker(args, api_url)
            ai_tracker.start()
            _print("Launcher", f"AI tracker active (polls every {args.watch_interval}s).")
            _print("Launcher", "  -> Add a camera, click its AI button, counting starts immediately.")

    # -- Summary -----------------------------------------------------------
    print()
    print("-" * 64)
    print(f"  Dashboard  : {dashboard_url}")
    if ai_tracker:
        h = "127.0.0.1" if args.preview_host == "0.0.0.0" else args.preview_host
        print(f"  AI Preview : http://{h}:{args.preview_port}/feed/<device_id>")
    print("  Press Ctrl+C to stop everything.")
    print("-" * 64)
    print()

    # -- Keep alive --------------------------------------------------------
    try:
        while True:
            time.sleep(1)
            if php_server and not php_server.is_alive():
                _print("Launcher", "WARNING: PHP server thread ended unexpectedly.")
                break
            if ai_tracker and not ai_tracker.is_alive():
                _print("Launcher", "AI tracker process ended. Dashboard still running.")
                ai_tracker = None
    except KeyboardInterrupt:
        print()
        _print("Launcher", "Ctrl+C received - shutting down ...")
    finally:
        if ai_tracker:
            ai_tracker.stop()
        if php_server:
            php_server.stop()
        _print("Launcher", "Goodbye.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
