<?php
// Central settings. Edit the values below to match your temple.

date_default_timezone_set('Asia/Kolkata');

return [
    // People already inside when the day starts
    'opening_occupancy'      => 0,

    // Maximum comfortable number of people inside the temple
    'capacity'               => 5000,

    // Crowd status thresholds (percent of capacity)
    'moderate_percent'       => 50,   // below this = Normal
    'high_percent'           => 80,   // at or above this = High

    // A device is "online" if it sent/polled data within this many seconds
    'online_timeout_seconds' => 60,

    // How many items to show in "Recent Activity"
    'recent_events_limit'    => 10,

    // Camera IP addresses to fetch counts directly from (PULL mode):
    // Add your ESP32 Camera IP addresses here, e.g.:
    // 'camera_ips' => ['http://192.168.1.105', 'http://192.168.1.106'],
    'camera_ips'             => [],

    // AI tracker bridge (tracker/yolo_counter.py).
    // The tracker posts readings to this endpoint and (optionally) serves an
    // annotated MJPEG preview that the dashboard can display.
    'tracker_api_url'        => 'http://127.0.0.1:8000/api/device_reading.php',
    'tracker_preview_host'   => '127.0.0.1:8090',
    'tracker_preview_port'   => 8090,

    // SQLite file (created automatically)
    'db_path'                => __DIR__ . '/../database/temple.sqlite',
];
