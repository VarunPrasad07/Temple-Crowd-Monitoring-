# ESP32-CAM YOLOv8 People Counter & Dashboard Bridge

This script reads the live video stream from your ESP32-CAM (or webcam), runs real-time person tracking with YOLOv8 & ByteTrack, and automatically sends live entry and exit counts to the Temple Crowd Monitoring Dashboard.

---

## 1. Installation

```bash
pip install -r requirements.txt
```

---

## 2. Running the Counter

### Connect to ESP32-CAM Stream:
```bash
python yolo_counter.py --url http://192.168.137.160:81/stream --device-id CAM-01 --gate-name "Main Gopuram Gate"
```

### Test with Local Webcam (Camera 0):
```bash
python yolo_counter.py --url 0 --device-id CAM-01 --gate-name "Entrance 1"
```

### Run in Headless Mode (no OpenCV GUI window, background server mode):
```bash
python yolo_counter.py --url http://192.168.137.160:81/stream --headless
```

---

## 3. Options & Tuning

| Argument | Default | Description |
|---|---|---|
| `--url` | `http://192.168.137.160:81/stream` | Stream URL or camera index (0) |
| `--api-url` | `http://127.0.0.1:8000/api/device_reading.php` | Dashboard ingest API |
| `--device-id` | `CAM-01` | Camera ID shown on dashboard |
| `--gate-name` | `Main Gopuram Gate` | Physical gate label |
| `--orientation` | `vertical` | `vertical` (left<->right) or `horizontal` (top<->bottom) |
| `--line-pos` | `0.5` | Fractional position of crossing line (0.0 to 1.0) |
| `--invert` | `True` | Swap which crossing direction counts as IN vs OUT |
| `--conf` | `0.4` | Detection confidence threshold |
| `--headless` | `False` | Run without GUI window |

---

## 4. How It Communicates with the Dashboard

1. **Heartbeat (Every 10s)**: Sends a lightweight ping so the camera shows as **Online** on the dashboard.
2. **Immediate Event (On Crossing)**: When someone crosses the line, sends an HTTP POST:
   ```json
   {
     "device_id": "CAM-01",
     "gate_name": "Main Gopuram Gate",
     "direction": "entry",
     "count": 1,
     "ip": "http://192.168.137.160:81/stream"
   }
   ```
3. All network requests run in a **background thread**, guaranteeing that video frame processing and detection are never delayed.
