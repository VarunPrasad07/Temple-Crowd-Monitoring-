# Temple Crowd Monitoring & AI Prediction Dashboard

HTML + CSS + JavaScript frontend, PHP API, SQLite database, and ESP32-CAM devices communicating counts.

## Folder structure

```
temple-crowd-dashboard/
├── index.html                     # Live monitoring & prediction dashboard
├── README.md                      # Documentation & hardware connection guide
│
├── assets/
│   ├── css/style.css              # Warm temple ivory & sacred saffron stylesheet
│   └── js/app.js                  # Real-time polling, IP management & UI renderer (every 5s)
│
├── api/
│   ├── config.php                 # Capacity, crowd thresholds, timeout configs
│   ├── db.php                     # SQLite connection & table auto-creation
│   ├── devices.php                # Add, list, and delete manual Camera IP devices
│   ├── device_reading.php         # Ingestion endpoint for ESP32-CAM POST readings
│   ├── stats.php                  # Aggregates entries, exits, gates & prediction
│   └── helpers.php                # JSON response utility functions
│
├── database/
│   └── temple.sqlite              # Persistent SQLite database file
│
└── esp32/
    └── esp32_cam_post.ino         # Arduino C++ firmware for ESP32-CAM (with WebServer)
```

## 1. Run it locally

From the project folder, run PHP's built-in web server:

```bash
php -S 127.0.0.1:8000
```

Open **http://localhost:8000** in your browser. The dashboard will automatically update every 5 seconds.

## 2. Manually Adding Camera IP from Dashboard UI

You can add a camera IP directly from the browser:
1. In the **Gate Monitoring** panel, click the **"+ Add Camera IP"** button.
2. Enter the camera details:
   - **Camera IP Address** (e.g. `192.168.1.105`)
   - **Gate Name** (e.g. `Main Entrance Gopuram`)
   - **Device ID** (e.g. `CAM-01`)
   - **Direction** (`Entry` or `Exit`)
3. Click **Connect & Save**.
4. The system immediately registers the camera into SQLite and automatically polls its counts every 5 seconds!
5. To remove a camera, click the **Delete (Trash)** button in the table's Action column.

## 3. Settings

Edit `api/config.php`:

- `opening_occupancy`: baseline morning count (default 0)
- `capacity`: temple maximum capacity (default 5000)
- `moderate_percent`: 50% threshold for Moderate status
- `high_percent`: 80% threshold for High status
- `online_timeout_seconds`: 60s without heartbeat marks device offline

**Occupancy = opening occupancy + today's entries − today's exits** (never below 0).

## 4. API Reference

**POST / GET / DELETE `api/devices.php`**
- `POST`: `{ "ip_address": "192.168.1.105", "gate_name": "Main Gate", "device_id": "CAM-01", "direction": "entry" }`
- `GET`: Lists all registered camera IP devices.
- `DELETE`: `{ "device_id": "CAM-01" }` or `?device_id=CAM-01`.

**POST `api/device_reading.php`** (Push mode)

| Field       | Required | Notes |
| ----------- | -------- | ----- |
| `device_id` | yes      | Unique per device, e.g. `CAM-01`. |
| `direction` | yes      | `entry` or `exit`. |
| `count`     | no       | People counted (default 0). `0` = heartbeat keep-alive. |
| `gate_name` | no       | Shown on the dashboard. |
| `ip`        | no       | Camera IP address. |

**GET `api/stats.php`**
Returns:
- `summary`: `entries`, `exits`, `occupancy`, `occupancy_percent`, `crowd_status`
- `prediction`: `current_crowd`, `expected_crowd`, `approx_change`, `status_text`, `status_level`
- `devices`: `total`, `online`, `status`
- `gates`: gate-by-gate counts, camera IP addresses (`ip_address`), and online status
- `recent`: last 10 count events with timestamps

## 5. Connect Real ESP32-CAM

1. Connect the computer and the ESP32-CAM to the **same Wi-Fi router**.
2. Flash `esp32/esp32_cam_post.ino` to your ESP32-CAM.
3. Open Serial Monitor at 115200 baud to find your Camera IP (e.g. `192.168.1.105`).
4. On your dashboard (**http://localhost:8000**), click **"+ Add Camera IP"**, type `192.168.1.105`, and click Save!
