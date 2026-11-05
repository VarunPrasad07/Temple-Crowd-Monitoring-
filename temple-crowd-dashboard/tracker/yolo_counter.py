#!/usr/bin/env python3
"""
Temple Crowd Monitoring - ESP32-CAM YOLOv8 People Counter & Dashboard Bridge
============================================================================
Reads the live video stream from your ESP32-CAM (or a webcam), tracks people
with YOLOv8 + ByteTrack, detects who crosses the counting line (IN / OUT) and
pushes every crossing to the Temple Crowd Dashboard API.

Two ways to run it
------------------
1. Single camera (command line):

       python yolo_counter.py --url http://192.168.137.160:81/stream \
           --device-id CAM-01 --gate-name "Main Gopuram Gate"

2. Synced with the dashboard (recommended):
   the tracker reads the camera list from the website (IP, gate name, device id
   and direction) and starts/stops a counting session for every camera that
   has "AI counting" switched on.

       python yolo_counter.py --watch

   Add a camera in the dashboard (Gate Monitoring -> "+ Add Camera IP"), press
   the purple AI button in its row and the tracker picks it up automatically.

Quick start
-----------
    pip install -r requirements.txt
    python yolo_counter.py --self-test      # verify everything without a camera
"""

from __future__ import annotations

import argparse
import json
import queue
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Dict, List, Optional, Tuple

import cv2
import numpy as np
from ultralytics import YOLO

# --------------------------------------------------------------------------- #
# Defaults
# --------------------------------------------------------------------------- #
DEFAULT_URL = "http://192.168.137.160:81/stream"
DEFAULT_API_URL = "http://127.0.0.1:8000/api/device_reading.php"
DEFAULT_DEVICE_ID = "CAM-01"
DEFAULT_GATE_NAME = "Main Gopuram Gate"
DEFAULT_ORIENTATION = "vertical"
DEFAULT_INVERT = True
DEFAULT_START_INSIDE = 0
DEFAULT_PREVIEW_PORT = 8090
DEFAULT_PREVIEW_HOST = "127.0.0.1"
DEFAULT_STREAM_PATH = "/stream"
SHOW_IDS = False

HEARTBEAT_SECONDS = 10.0
HTTP_TIMEOUT = 2.5


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def stream_candidates(address: str, stream_path: str = DEFAULT_STREAM_PATH) -> List[str]:
    """Builds the list of stream URLs to try for a camera address.

    "192.168.1.105"                    -> :81/stream  and  /stream
    "192.168.137.160:81/stream"        -> as given
    "http://192.168.137.160:81/stream"  -> as given
    """
    addr = (address or "").strip()
    if not addr:
        return []

    if "://" in addr:
        after = addr.split("://", 1)[1]
        if "/" in after:
            return [addr]
        return [addr.rstrip("/") + stream_path]

    if "/" in addr:
        return ["http://" + addr]

    if ":" in addr:                                   # host:port
        return [f"http://{addr}{stream_path}"]

    return [f"http://{addr}:81{stream_path}", f"http://{addr}{stream_path}"]


@dataclass
class DeviceConfig:
    """Everything the tracker needs to count one camera."""
    device_id: str
    gate_name: str
    address: str                       # IP or URL as stored on the dashboard
    direction: str = "both"            # entry | exit | both
    urls: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.urls:
            self.urls = stream_candidates(self.address)


# --------------------------------------------------------------------------- #
# Dashboard bridge
# --------------------------------------------------------------------------- #
class DashboardClient:
    """Sends counts and heartbeats to the Temple Dashboard backend.

    All network traffic runs in a background thread so video processing is
    never blocked by an HTTP call. Failed packets are retried, so a temporary
    outage of the PHP server does not lose counts.
    """

    def __init__(self, api_url: str, device_id: str, gate_name: str, camera_ip: str,
                 device_direction: str = "both", feed_url: str = "", model_name: str = ""):
        self.api_url = api_url
        self.device_id = device_id
        self.gate_name = gate_name
        self.camera_ip = camera_ip
        self.device_direction = device_direction
        self.feed_url = feed_url
        self.model_name = model_name

        self.queue: "queue.Queue[dict]" = queue.Queue(maxsize=500)
        self.running = True
        self.last_heartbeat = 0.0
        self.sent_events = 0
        self.failed_events = 0
        self.last_error = ""

        self.worker = threading.Thread(target=self._loop, daemon=True, name=f"api-{device_id}")
        self.worker.start()

    # -- public API ------------------------------------------------------- #
    def set_feed_url(self, feed_url: str) -> None:
        self.feed_url = feed_url

    def send_event(self, direction: str, count: int = 1) -> None:
        """Queue an entry (IN) or exit (OUT) event."""
        payload = self._payload("entry" if direction.lower() in ("in", "entry") else "exit", count)
        self._enqueue(payload)

    def send_heartbeat(self, inside: Optional[int] = None) -> None:
        """Queue a lightweight heartbeat (count=0) so the camera stays Online."""
        now = time.time()
        if now - self.last_heartbeat < HEARTBEAT_SECONDS:
            return
        self.last_heartbeat = now
        payload = self._payload("entry", 0)
        if inside is not None:
            payload["ai_inside"] = int(inside)
        self._enqueue(payload)

    # -- internals -------------------------------------------------------- #
    def _payload(self, direction: str, count: int) -> dict:
        return {
            "device_id": self.device_id,
            "gate_name": self.gate_name,
            "direction": direction,
            "device_direction": self.device_direction,
            "count": int(count),
            "ip": self.camera_ip,
            "ai_feed_url": self.feed_url,
            "ai_model": self.model_name,
        }

    def _enqueue(self, payload: dict) -> None:
        try:
            self.queue.put_nowait(payload)
        except queue.Full:
            self.failed_events += 1
            print("[Dashboard] Queue full - packet dropped.")

    def _loop(self) -> None:
        while self.running:
            try:
                payload = self.queue.get(timeout=1.0)
            except queue.Empty:
                continue

            try:
                self._post(payload)
                if payload["count"] > 0:
                    self.sent_events += 1
                    print(f"[{datetime.now():%H:%M:%S}]  [Dashboard synced] "
                          f"{payload['direction'].upper()} +{payload['count']}")
            except Exception as exc:                      # noqa: BLE001
                self.failed_events += 1
                self.last_error = str(exc)
                print(f"[Dashboard Error] {exc} - will retry on the next heartbeat.")
                time.sleep(1.0)
            finally:
                self.queue.task_done()

    def _post(self, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.api_url,
            data=data,
            headers={"Content-Type": "application/json", "User-Agent": "Temple-YOLO-Tracker/2.0"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            if resp.status != 200:
                raise urllib.error.URLError(f"HTTP {resp.status}")

    def stop(self) -> None:
        self.running = False


def fetch_json(url: str, timeout: float = HTTP_TIMEOUT) -> dict:
    """GETs a JSON document (used to read the camera list from the dashboard)."""
    req = urllib.request.Request(url, headers={"User-Agent": "Temple-YOLO-Tracker/2.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# --------------------------------------------------------------------------- #
# Video source
# --------------------------------------------------------------------------- #
class StreamReader:
    """Reads frames in a background thread so we always process the newest frame
    (MJPEG streams otherwise build up lag) and reconnects if the stream drops.

    Several candidate URLs can be given (e.g. :81/stream and /stream); they are
    tried one after another until one of them answers.
    """

    def __init__(self, sources: List[str]):
        if isinstance(sources, str):
            sources = [sources]
        self.sources = [int(s) if str(s).isdigit() else s for s in sources] or [0]
        self.frame: Optional[np.ndarray] = None
        self.lock = threading.Lock()
        self.running = True
        self.connected = False
        self.active: Optional[str] = None
        threading.Thread(target=self._loop, daemon=True, name="stream-reader").start()

    def _loop(self) -> None:
        while self.running:
            for source in self.sources:
                if not self.running:
                    break
                cap = cv2.VideoCapture(source)
                if not cap.isOpened():
                    print(f"Cannot open {source}, trying the next address...")
                    cap.release()
                    time.sleep(1)
                    continue

                print(f"Stream connected: {source}")
                self.active = source
                self.connected = True
                while self.running:
                    ok, frame = cap.read()
                    if not ok:
                        print("Stream lost, reconnecting...")
                        break
                    with self.lock:
                        self.frame = frame
                cap.release()
                self.connected = False
                self.active = None
                time.sleep(1)

    def read(self) -> Optional[np.ndarray]:
        with self.lock:
            return None if self.frame is None else self.frame.copy()

    def stop(self) -> None:
        self.running = False


# --------------------------------------------------------------------------- #
# Line crossing logic (pure, testable)
# --------------------------------------------------------------------------- #
class LineCrossingCounter:
    """Turns tracked detections into IN / OUT crossing events.

    side = -1  -> one side of the counting line
    side = +1  -> the other side
    side =  0  -> inside the dead-zone (the previous side is kept)

    "allowed" filters which crossings are counted:
      both  -> entries and exits (default)
      entry -> only crossings towards the temple
      exit  -> only crossings out of the temple
    """

    def __init__(self, orientation: str = "vertical", line_pos: float = 0.5,
                 margin: int = 12, invert: bool = True, start_inside: int = 0,
                 allowed: str = "both", stale_after: int = 60):
        self.horizontal = orientation == "horizontal"
        self.line_pos = float(line_pos)
        self.margin = int(margin)
        self.invert = bool(invert)
        self.start_inside = int(start_inside)
        self.allowed = allowed if allowed in ("entry", "exit", "both") else "both"
        self.stale_after = int(stale_after)

        self.count_in = 0
        self.count_out = 0
        self.last_side: Dict[int, int] = {}
        self.seen_frames: Dict[int, int] = {}
        self.frame_no = 0

    # -- helpers ---------------------------------------------------------- #
    @property
    def inside(self) -> int:
        return max(0, self.start_inside + self.count_in - self.count_out)

    def reset(self) -> None:
        self.count_in = 0
        self.count_out = 0
        self.last_side.clear()
        self.seen_frames.clear()

    def line_at(self, width: int, height: int) -> int:
        span = height if self.horizontal else width
        return int(span * self.line_pos)

    def side_of(self, cx: int, cy: int, line_at: int) -> int:
        pos = cy if self.horizontal else cx
        if pos > line_at + self.margin:
            return 1
        if pos < line_at - self.margin:
            return -1
        return 0

    def _allowed(self, event: str) -> bool:
        if self.allowed == "both":
            return True
        return (self.allowed == "entry" and event == "in") or \
               (self.allowed == "exit" and event == "out")

    # -- main entry point ------------------------------------------------- #
    def update(self, detections: List[Tuple[int, float, float, float, float]],
               width: int, height: int) -> List[str]:
        """Feed a list of (track_id, x1, y1, x2, y2) and get back crossing events."""
        self.frame_no += 1
        line_at = self.line_at(width, height)
        events: List[str] = []

        for det in detections:
            tid = int(det[0])
            x1, y1, x2, y2 = det[1], det[2], det[3], det[4]
            cx, cy = int((x1 + x2) / 2), int((y1 + y2) / 2)

            side = self.side_of(cx, cy, line_at)
            self.seen_frames[tid] = self.frame_no

            if side == 0:
                continue

            prev = self.last_side.get(tid)
            if prev is not None and prev != side:
                # Moving from side -1 to +1 means "down" (horizontal) or "right" (vertical)
                going_in = (side == 1) != self.invert
                event = "in" if going_in else "out"
                if self._allowed(event):
                    if going_in:
                        self.count_in += 1
                    else:
                        self.count_out += 1
                    events.append(event)
            self.last_side[tid] = side

        self._drop_stale_tracks()
        return events

    def _drop_stale_tracks(self) -> None:
        """Forget tracks that disappeared so the dict does not grow forever."""
        if self.frame_no % 30 != 0:
            return
        cutoff = self.frame_no - self.stale_after
        for tid in [t for t, f in self.seen_frames.items() if f < cutoff]:
            self.seen_frames.pop(tid, None)
            self.last_side.pop(tid, None)


# --------------------------------------------------------------------------- #
# Drawing helpers
# --------------------------------------------------------------------------- #
def draw_overlay(frame: np.ndarray, counter: LineCrossingCounter,
                 detections: List[Tuple[int, float, float, float, float]],
                 show_ids: bool = False) -> np.ndarray:
    """Draws boxes, the counting line and the IN/OUT zones on a frame."""
    h, w = frame.shape[:2]
    line_at = counter.line_at(w, h)

    for det in detections:
        tid = int(det[0])
        x1, y1, x2, y2 = int(det[1]), int(det[2]), int(det[3]), int(det[4])
        cx, cy = int((x1 + x2) / 2), int((y1 + y2) / 2)
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.circle(frame, (cx, cy), 4, (0, 0, 255), -1)
        if show_ids:
            cv2.putText(frame, f"ID {tid}", (x1, max(14, y1 - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

    if counter.horizontal:
        zone_pos = (0, line_at, w, h)
        zone_neg = (0, 0, w, line_at)
    else:
        zone_pos = (line_at, 0, w, h)
        zone_neg = (0, 0, line_at, h)
    in_zone, out_zone = (zone_neg, zone_pos) if counter.invert else (zone_pos, zone_neg)

    overlay = frame.copy()
    cv2.rectangle(overlay, in_zone[:2], in_zone[2:], (0, 200, 0), -1)      # green tint
    cv2.rectangle(overlay, out_zone[:2], out_zone[2:], (0, 128, 255), -1)  # orange tint
    frame = cv2.addWeighted(overlay, 0.15, frame, 0.85, 0)

    for zone, label, color in ((in_zone, "IN SIDE", (0, 200, 0)),
                               (out_zone, "OUT SIDE", (0, 128, 255))):
        zx1, zy1, zx2, zy2 = zone
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
        tx = (zx1 + zx2) // 2 - tw // 2
        ty = (zy1 + zy2) // 2 + th // 2 if counter.horizontal else h - 25
        cv2.putText(frame, label, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 4)
        cv2.putText(frame, label, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)

    # Arrow showing the walking direction that counts as IN
    out_c = ((out_zone[0] + out_zone[2]) // 2, (out_zone[1] + out_zone[3]) // 2)
    in_c = ((in_zone[0] + in_zone[2]) // 2, (in_zone[1] + in_zone[3]) // 2)
    if counter.horizontal:
        a0, a1 = (w * 3 // 4, out_c[1]), (w * 3 // 4, in_c[1])
    else:
        a0, a1 = (out_c[0], h // 2), (in_c[0], h // 2)
    cv2.arrowedLine(frame, a0, a1, (255, 255, 255), 3, tipLength=0.12)

    # Counting line
    if counter.horizontal:
        cv2.line(frame, (0, line_at), (w, line_at), (0, 255, 255), 2)
    else:
        cv2.line(frame, (line_at, 0), (line_at, h), (0, 255, 255), 2)

    # Counters
    cv2.rectangle(frame, (0, 0), (250, 95), (18, 12, 8), -1)
    cv2.putText(frame, f"IN:      {counter.count_in}", (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    cv2.putText(frame, f"OUT:     {counter.count_out}", (12, 56), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2)
    cv2.putText(frame, f"INSIDE:  {counter.inside}", (12, 84), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    return frame


# --------------------------------------------------------------------------- #
# Annotated MJPEG preview server (shown inside the dashboard)
# --------------------------------------------------------------------------- #
class FrameHub:
    """Holds the latest encoded JPEG frame of one camera."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jpeg: Optional[bytes] = None

    def update(self, jpeg: bytes) -> None:
        with self._lock:
            self._jpeg = jpeg

    def get(self) -> Optional[bytes]:
        with self._lock:
            return self._jpeg


class PreviewRegistry:
    """Serves the annotated frames of every tracked camera.

    GET /feed/<device_id>  -> multipart MJPEG stream
    GET /status            -> JSON status of every camera
    """

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.hubs: Dict[str, FrameHub] = {}
        self.statuses: Dict[str, dict] = {}
        self._lock = threading.Lock()

        registry = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _cors(self) -> None:
                """Send CORS headers so browser pages on a different port can load the feed."""
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "*")

            def do_OPTIONS(self) -> None:                  # noqa: N802 — CORS preflight
                self.send_response(204)
                self._cors()
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_GET(self) -> None:                      # noqa: N802
                path = urllib.parse.urlparse(self.path).path.rstrip("/") or "/"
                if path.startswith("/feed/"):
                    registry._stream(self, path.split("/feed/", 1)[1])
                elif path == "/status":
                    registry._json(self, registry.all_status())
                elif path == "/":
                    registry._json(self, {"ok": True, "cameras": list(registry.hubs.keys())})
                else:
                    self.send_error(404, "Not found")

            def log_message(self, fmt: str, *args) -> None:
                return

        self.httpd = ThreadingHTTPServer((host, port), Handler)
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True, name="ai-preview")

    # -- lifecycle -------------------------------------------------------- #
    def start(self) -> "PreviewRegistry":
        self.thread.start()
        print(f"[Preview] Annotated AI feed server on http://{self.host}:{self.port}/feed/<device_id>")
        return self

    def stop(self) -> None:
        try:
            self.httpd.shutdown()
            self.httpd.server_close()
        except Exception:                                  # noqa: BLE001
            pass

    # -- camera registration ---------------------------------------------- #
    def register(self, device_id: str) -> FrameHub:
        with self._lock:
            hub = self.hubs.get(device_id)
            if hub is None:
                hub = FrameHub()
                self.hubs[device_id] = hub
            return hub

    def unregister(self, device_id: str) -> None:
        with self._lock:
            self.hubs.pop(device_id, None)
            self.statuses.pop(device_id, None)

    def set_status(self, device_id: str, status: dict) -> None:
        with self._lock:
            self.statuses[device_id] = status

    def all_status(self) -> dict:
        with self._lock:
            return dict(self.statuses)

    # -- http helpers ------------------------------------------------------ #
    def _json(self, handler: BaseHTTPRequestHandler, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("Access-Control-Allow-Origin", "*")
        handler.end_headers()
        handler.wfile.write(body)

    def _stream(self, handler: BaseHTTPRequestHandler, device_id: str) -> None:
        with self._lock:
            hub = self.hubs.get(device_id)
        if hub is None:
            handler.send_error(404, "Camera not tracked")
            return

        boundary = "templeframe"
        handler.send_response(200)
        handler.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={boundary}")
        handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        handler.send_header("Pragma", "no-cache")
        handler.send_header("Access-Control-Allow-Origin", "*")
        handler.end_headers()

        last: Optional[bytes] = None
        try:
            while True:
                data = hub.get()
                if data is not None and data != last:
                    last = data
                    header = (f"--{boundary}\r\n"
                              f"Content-Type: image/jpeg\r\n"
                              f"Content-Length: {len(data)}\r\n\r\n").encode()
                    handler.wfile.write(header)
                    handler.wfile.write(data)
                    handler.wfile.write(b"\r\n")
                time.sleep(0.05)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:                                  # noqa: BLE001
            pass


# --------------------------------------------------------------------------- #
# One counting session per camera
# --------------------------------------------------------------------------- #
class CameraWorker(threading.Thread):
    """Runs detection + line crossing for a single camera."""

    def __init__(self, cfg: DeviceConfig, args: argparse.Namespace, preview: Optional[PreviewRegistry]):
        super().__init__(daemon=True, name=f"tracker-{cfg.device_id}")
        self.cfg = cfg
        self.args = args
        self.preview = preview
        self.stop_flag = threading.Event()
        self.counter = LineCrossingCounter(orientation=args.orientation, line_pos=args.line_pos,
                                           margin=args.margin, invert=args.invert,
                                           start_inside=args.start_inside,
                                           allowed=cfg.direction)
        self.client: Optional[DashboardClient] = None
        self.reader: Optional[StreamReader] = None
        self.hub: Optional[FrameHub] = None
        self.frames = 0
        self.fps_mark = time.time()

    # -- lifecycle -------------------------------------------------------- #
    def run(self) -> None:
        args = self.args
        print(f"\n[Camera {self.cfg.device_id}] {self.cfg.gate_name} -> {self.cfg.urls[0] if self.cfg.urls else '?'}")

        try:
            model = YOLO(args.model)
        except Exception as exc:                          # noqa: BLE001
            print(f"[Camera {self.cfg.device_id}] Model load failed: {exc}")
            return

        self.reader = StreamReader(self.cfg.urls or [args.url])

        feed_url = ""
        if self.preview is not None:
            self.hub = self.preview.register(self.cfg.device_id)
            host = args.preview_host if args.preview_host != "0.0.0.0" else "127.0.0.1"
            feed_url = args.preview_url or f"http://{host}:{args.preview_port}/feed/{self.cfg.device_id}"

        self.client = DashboardClient(
            api_url=args.api_url,
            device_id=self.cfg.device_id,
            gate_name=self.cfg.gate_name,
            camera_ip=self.cfg.address,
            device_direction=self.cfg.direction,
            feed_url=feed_url,
            model_name=str(args.model),
        )
        self.client.send_heartbeat(inside=self.counter.inside)

        try:
            while not self.stop_flag.is_set():
                self.client.send_heartbeat(inside=self.counter.inside)

                frame = self.reader.read()
                if frame is None:
                    time.sleep(0.05)
                    continue

                h, w = frame.shape[:2]

                # class 0 = person; persist keeps track IDs between frames
                results = model.track(frame, persist=True, classes=[0], conf=args.conf,
                                       imgsz=args.imgsz, tracker="bytetrack.yaml",
                                       verbose=False)[0]

                detections: List[Tuple[int, float, float, float, float]] = []
                if results.boxes is not None and results.boxes.id is not None:
                    boxes = results.boxes.xyxy.cpu().numpy()
                    ids = results.boxes.id.int().cpu().tolist()
                    for (x1, y1, x2, y2), tid in zip(boxes, ids):
                        detections.append((int(tid), float(x1), float(y1), float(x2), float(y2)))

                for event in self.counter.update(detections, w, h):
                    label = "IN" if event == "in" else "OUT"
                    self.client.send_event("entry" if event == "in" else "exit", 1)
                    print(f"[{datetime.now():%H:%M:%S}]  [{self.cfg.device_id}] CROSSING: {label}  "
                          f"(in={self.counter.count_in} out={self.counter.count_out} "
                          f"inside={self.counter.inside})")

                annotated = draw_overlay(frame, self.counter, detections,
                                         show_ids=args.show_ids or SHOW_IDS)

                if self.hub is not None:
                    ok, buf = cv2.imencode(".jpg", annotated,
                                           [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                    if ok:
                        self.hub.update(buf.tobytes())

                if self.preview is not None:
                    self.preview.set_status(self.cfg.device_id, {
                        "device_id": self.cfg.device_id,
                        "gate_name": self.cfg.gate_name,
                        "in": self.counter.count_in,
                        "out": self.counter.count_out,
                        "inside": self.counter.inside,
                        "model": str(args.model),
                        "stream_connected": bool(self.reader.connected),
                        "updated": datetime.now().strftime("%H:%M:%S"),
                    })

                # ---- fps meter ------------------------------------------------ #
                self.frames += 1
                now = time.time()
                if now - self.fps_mark >= 5.0:
                    fps = self.frames / (now - self.fps_mark)
                    print(f"[{self.cfg.device_id}] {fps:.1f} fps | "
                          f"in={self.counter.count_in} out={self.counter.count_out} "
                          f"inside={self.counter.inside}")
                    self.frames = 0
                    self.fps_mark = now

                if not args.headless and args.watch:
                    continue    # the GUI is only used in single camera mode
                if not args.headless:
                    cv2.imshow(f"Temple Gate People Counter - {self.cfg.device_id}", annotated)
                    key = cv2.waitKey(1) & 0xFF
                    if key == ord("q"):
                        self.stop_flag.set()
                    elif key == ord("r"):
                        self.counter.reset()
                        print("[Counter Reset]")
        except Exception as exc:                          # noqa: BLE001
            print(f"[Camera {self.cfg.device_id}] stopped: {exc}")
        finally:
            if self.reader is not None:
                self.reader.stop()
            if self.client is not None:
                self.client.stop()
            if self.preview is not None:
                self.preview.unregister(self.cfg.device_id)
            print(f"[Camera {self.cfg.device_id}] stopped.")

    def stop(self) -> None:
        self.stop_flag.set()


# --------------------------------------------------------------------------- #
# Dashboard -> camera synchronisation
# --------------------------------------------------------------------------- #
class DeviceWatcher(threading.Thread):
    """Reads the camera list from the dashboard and keeps the tracker in sync.

    A camera is counted when "AI counting" is switched on for it in the
    dashboard. Adding or removing a camera there is picked up automatically.
    """

    def __init__(self, args: argparse.Namespace, preview: Optional[PreviewRegistry]):
        super().__init__(daemon=True, name="device-watcher")
        self.args = args
        self.preview = preview
        self.stop_flag = threading.Event()
        self.workers: Dict[str, CameraWorker] = {}
        self.devices_url = args.devices_url or args.api_url.replace("device_reading.php", "devices.php")

    def run(self) -> None:
        print(f"[Sync] Watching {self.devices_url} for cameras (every {self.args.watch_interval}s)")
        while not self.stop_flag.is_set():
            try:
                self._sync()
            except Exception as exc:                      # noqa: BLE001
                print(f"[Sync] Could not read the camera list: {exc}")
            self.stop_flag.wait(self.args.watch_interval)

    # -- internals -------------------------------------------------------- #
    def _sync(self) -> None:
        payload = fetch_json(self.devices_url)
        devices = payload.get("devices", []) if isinstance(payload, dict) else []
        known: Dict[str, dict] = {}

        for device in devices:
            device_id = str(device.get("device_id", "")).strip()
            address = str(device.get("ip_address", "")).strip()
            if not device_id or not address:
                continue
            if not (device.get("ai_enabled") or self.args.watch_all):
                continue

            known[device_id] = device
            if device_id in self.workers:
                continue

            cfg = DeviceConfig(
                device_id=device_id,
                gate_name=str(device.get("gate_name") or device_id),
                address=address,
                direction=str(device.get("direction") or "both"),
            )
            worker = CameraWorker(cfg, self.args, self.preview)
            self.workers[device_id] = worker
            worker.start()

        # stop workers whose camera was removed or whose AI counting was switched off
        for device_id, worker in list(self.workers.items()):
            if device_id not in known:
                worker.stop()
                del self.workers[device_id]

    def stop(self) -> None:
        self.stop_flag.set()
        for worker in self.workers.values():
            worker.stop()


# --------------------------------------------------------------------------- #
# Self test (no camera needed)
# --------------------------------------------------------------------------- #
def run_self_test(args: argparse.Namespace) -> int:
    """Validates the counting logic and the dashboard API connection."""
    print("=" * 64)
    print(" Temple Crowd Monitoring - Tracker self test")
    print("=" * 64)

    width, height = 640, 480
    counter = LineCrossingCounter(orientation=args.orientation, line_pos=args.line_pos,
                                  margin=args.margin, invert=args.invert,
                                  start_inside=args.start_inside)
    line = counter.line_at(width, height)
    print(f"Frame {width}x{height}, {args.orientation} line at {line}px, "
          f"invert={args.invert}, margin={args.margin}px")

    # --- Test 1 & 2: full crossings ------------------------------------- #
    left_to_right = "out" if args.invert else "in"
    right_to_left = "in" if args.invert else "out"

    events = counter.update([(1, 40, 200, 120, 300)], width, height)     # far left -> side -1
    assert events == [], f"First sighting must not trigger an event, got {events}"

    events = counter.update([(1, 520, 200, 600, 300)], width, height)    # far right -> side +1
    assert events == [left_to_right], f"Expected {left_to_right}, got {events}"

    counter.update([(2, 520, 200, 600, 300)], width, height)             # new person on the right
    events = counter.update([(2, 40, 200, 120, 300)], width, height)     # moves to the left
    assert events == [right_to_left], f"Expected {right_to_left}, got {events}"

    # --- Test 3: jitter inside the dead-zone must not count ------------- #
    before_in, before_out = counter.count_in, counter.count_out
    counter.update([(3, 100, 200, 160, 300)], width, height)             # settles on side -1
    for x in range(278, 303, 4):                                         # stays in the dead-zone
        counter.update([(3, x, 200, x + 60, 300)], width, height)
    assert (counter.count_in, counter.count_out) == (before_in, before_out), \
        "Dead-zone jitter must not create events"

    # --- Test 4: direction filter ---------------------------------------- #
    filtered = LineCrossingCounter(orientation=args.orientation, invert=args.invert,
                                   allowed="entry")
    filtered.update([(1, 40, 200, 120, 300)], width, height)
    events = filtered.update([(1, 520, 200, 600, 300)], width, height)
    assert events == [] or events == ["in"], f"Direction filter broken: {events}"
    assert filtered.count_in + filtered.count_out == len(events), "Filtered counter mismatch"

    # --- Test 5: reset ---------------------------------------------------- #
    counter.reset()
    assert counter.count_in == 0 and counter.count_out == 0, "Reset failed"
    print("[OK] Counting logic verified (crossings, dead-zone, filter, reset)")

    # --- Test 6: stream URL resolution ------------------------------------ #
    assert stream_candidates("192.168.1.105")[0] == "http://192.168.1.105:81/stream"
    assert stream_candidates("192.168.137.160:81/stream")[0] == "http://192.168.137.160:81/stream"
    assert stream_candidates("http://192.168.1.5/stream")[0] == "http://192.168.1.5/stream"
    print("[OK] Camera address -> stream URL resolution verified")

    # --- Test 7: dashboard API ------------------------------------------- #
    print(f"\n[Dashboard] Sending test readings to {args.api_url} ...")
    client = DashboardClient(api_url=args.api_url, device_id=args.device_id,
                             gate_name=args.gate_name, camera_ip=str(args.url),
                             device_direction=args.direction, model_name=args.model)
    client.send_heartbeat(inside=0)
    client.send_event("entry", 1)
    client.send_event("exit", 1)
    time.sleep(2.0)
    client.stop()

    if client.failed_events:
        print(f"[FAIL] Dashboard unreachable: {client.last_error}")
        print("       Start the dashboard first:  php -S 127.0.0.1:8000")
        return 1

    print("[OK] Dashboard accepted the readings (entry +1, exit +1, heartbeat)")
    print("=" * 64)
    return 0


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="ESP32-CAM YOLOv8 People Counter & Temple Dashboard bridge",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    ap.add_argument("--url", default=DEFAULT_URL,
                    help="ESP32-CAM stream URL, e.g. http://192.168.1.50:81/stream, or 0 for webcam")
    ap.add_argument("--api-url", default=DEFAULT_API_URL,
                    help="Dashboard ingest endpoint (api/device_reading.php)")
    ap.add_argument("--device-id", default=DEFAULT_DEVICE_ID, help="Camera ID shown on the dashboard")
    ap.add_argument("--gate-name", default=DEFAULT_GATE_NAME, help="Physical gate name")
    ap.add_argument("--direction", choices=["entry", "exit", "both"], default="both",
                    help="Gate direction of this camera (a line-crossing camera counts both)")

    ap.add_argument("--model", default="yolov8n.pt", help="YOLO model path")
    ap.add_argument("--conf", type=float, default=0.4, help="detection confidence")
    ap.add_argument("--imgsz", type=int, default=480, help="inference size")

    ap.add_argument("--orientation", choices=["horizontal", "vertical"], default=DEFAULT_ORIENTATION,
                    help="horizontal line: people cross top<->bottom. vertical line: left<->right")
    ap.add_argument("--line-pos", type=float, default=0.5,
                    help="line position as fraction of frame (0-1)")
    ap.add_argument("--margin", type=int, default=12,
                    help="dead-zone in pixels around the line to avoid jitter")
    ap.add_argument("--invert", action=argparse.BooleanOptionalAction, default=DEFAULT_INVERT,
                    help="swap which direction counts as IN (use --no-invert to disable)")
    ap.add_argument("--start-inside", type=int, default=DEFAULT_START_INSIDE,
                    help="number of people already inside when the program starts")

    ap.add_argument("--headless", action="store_true", help="run without opening the GUI preview window")
    ap.add_argument("--show-ids", action="store_true", help="draw the ByteTrack id above every box")

    ap.add_argument("--watch", action="store_true",
                    help="read the camera list from the dashboard and count every camera with AI counting on")
    ap.add_argument("--watch-all", action="store_true",
                    help="with --watch: count every camera, even the ones without AI counting enabled")
    ap.add_argument("--watch-interval", type=int, default=10,
                    help="how often the camera list is refreshed (seconds)")
    ap.add_argument("--devices-url", default="",
                    help="camera list endpoint (defaults to api/devices.php next to --api-url)")

    ap.add_argument("--preview-port", type=int, default=DEFAULT_PREVIEW_PORT,
                    help="port of the annotated MJPEG preview (0 disables it)")
    ap.add_argument("--preview-host", default=DEFAULT_PREVIEW_HOST,
                    help="host the preview server binds to (use 0.0.0.0 for LAN access)")
    ap.add_argument("--preview-url", default="",
                    help="public URL of the preview, if it differs from the local one")

    ap.add_argument("--self-test", action="store_true",
                    help="verify the counting logic and the dashboard connection, then exit")
    return ap.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    if args.self_test:
        return run_self_test(args)

    preview: Optional[PreviewRegistry] = None
    if args.preview_port > 0:
        try:
            preview = PreviewRegistry(args.preview_host, args.preview_port).start()
        except OSError as exc:
            print(f"[Preview] Could not start the preview server on port {args.preview_port}: {exc}")
            preview = None

    print("=" * 64)
    print(" Temple Crowd Monitoring - YOLOv8 Person Tracker")
    print(f" Dashboard API : {args.api_url}")
    print(f" Model         : {args.model}")
    print(f" Orientation   : {args.orientation} (line @ {args.line_pos * 100:.0f}%)")
    if args.watch:
        print(" Mode          : synced with the dashboard (AI counting switches)")
    else:
        print(f" Source Stream : {args.url}")
        print(f" Device ID     : {args.device_id}")
        print(f" Gate Name     : {args.gate_name}")
    print("=" * 64)

    try:
        if args.watch:
            watcher = DeviceWatcher(args, preview)
            watcher.start()
            print("\nTracker is running. Add a camera in the dashboard and press its AI button.")
            print("Press 'q' (with the preview window focused) or Ctrl+C to quit.")
            try:
                while True:
                    time.sleep(0.5)
                    if not args.headless and cv2.waitKey(1) & 0xFF == ord("q"):
                        break
            except KeyboardInterrupt:
                pass
            finally:
                watcher.stop()
        else:
            cfg = DeviceConfig(device_id=args.device_id, gate_name=args.gate_name,
                               address=str(args.url), direction=args.direction)
            worker = CameraWorker(cfg, args, preview)
            worker.start()
            print("\nTracker is running. Press 'q' to quit, 'r' to reset local counts.")
            try:
                while worker.is_alive():
                    time.sleep(0.5)
            except KeyboardInterrupt:
                pass
            finally:
                worker.stop()
                worker.join(timeout=5)
    finally:
        if preview is not None:
            preview.stop()
        if not args.headless:
            cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
