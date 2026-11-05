<?php
// Receives a reading from an ESP32-CAM or from the AI (YOLO) tracker bridge.
//
// POST JSON example (ESP32-CAM firmware):
// {
//   "device_id": "CAM-01",
//   "gate_name": "Main Gate",
//   "direction": "entry",      // "entry", "exit" or "both"
//   "count": 3,                // people counted since last reading (0 = heartbeat only)
//   "ip": "192.168.1.105"      // optional: camera IP address / stream URL
// }
//
// Extra fields sent by tracker/yolo_counter.py:
// {
//   "device_direction": "both",           // gate direction of the AI camera
//   "ai_feed_url": "http://127.0.0.1:8090/feed/CAM-01",
//   "ai_inside": 42,                     // live people-inside reported by the tracker
//   "ai_model": "yolov8n.pt"
// }

require_once __DIR__ . '/db.php';

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    json_response(['ok' => false, 'error' => 'Use POST'], 405);
}

$data      = read_json_body();
$deviceId  = trim((string)($data['device_id'] ?? ''));
$gateName  = trim((string)($data['gate_name'] ?? ''));
$direction = strtolower(trim((string)($data['direction'] ?? '')));
$count     = isset($data['count']) ? (int)$data['count'] : 0;
$ipAddress = trim((string)($data['ip'] ?? $_SERVER['REMOTE_ADDR'] ?? ''));

$deviceDirection = strtolower(trim((string)($data['device_direction'] ?? '')));
$aiFeedUrl       = trim((string)($data['ai_feed_url'] ?? ''));
$aiModel         = trim((string)($data['ai_model'] ?? ''));
$aiInside        = isset($data['ai_inside']) ? (int)$data['ai_inside'] : null;

// The AI tracker always identifies itself with "device_direction" -> the camera
// is managed by the AI tracker and must be flagged as such on the dashboard.
$isAiTracker = $deviceDirection !== '';

// ---- Validate ----
if ($deviceId === '' || strlen($deviceId) > 50) {
    json_response(['ok' => false, 'error' => 'device_id is required (max 50 characters)'], 400);
}
if (!in_array($direction, ['entry', 'exit', 'both'], true)) {
    json_response(['ok' => false, 'error' => 'direction must be "entry", "exit", or "both"'], 400);
}
if ($count < 0 || $count > 1000) {
    json_response(['ok' => false, 'error' => 'count must be between 0 and 1000'], 400);
}
if ($deviceDirection !== '' && !in_array($deviceDirection, ['entry', 'exit', 'both'], true)) {
    $deviceDirection = '';
}
$gateName = substr($gateName, 0, 60);
$ipAddress = normalize_camera_url($ipAddress);
$aiFeedUrl = substr($aiFeedUrl, 0, 200);

// ---- Save ----
$db  = get_db();
$now = date('Y-m-d H:i:s');

$db->beginTransaction();

// Register the device the first time we see it, otherwise update it
$find = $db->prepare('SELECT id, direction FROM devices WHERE device_id = :d');
$find->execute([':d' => $deviceId]);
$existing = $find->fetch();

if ($existing) {
    // Decide the gate direction of the device:
    //  - an explicit "device_direction" from the AI tracker always wins
    //  - a device already marked "both" stays "both"
    //  - a device that reports two different directions becomes "both"
    if ($deviceDirection !== '') {
        $newDir = $deviceDirection;
    } elseif ($existing['direction'] === 'both') {
        $newDir = 'both';
    } elseif ($existing['direction'] !== $direction) {
        $newDir = 'both';
    } else {
        $newDir = $direction;
    }

    $db->prepare("UPDATE devices SET gate_name = COALESCE(NULLIF(:g, ''), gate_name),
                                     direction = :dir,
                                     ip_address = COALESCE(NULLIF(:ip, ''), ip_address),
                                     ai_feed_url = COALESCE(NULLIF(:feed, ''), ai_feed_url),
                                     ai_model = COALESCE(NULLIF(:model, ''), ai_model),
                                     ai_inside = COALESCE(:inside, ai_inside),
                                     ai_enabled = CASE WHEN :ai THEN 1 ELSE ai_enabled END,
                                     last_seen = :t
                  WHERE device_id = :d")
       ->execute([
           ':g'      => $gateName,
           ':dir'    => $newDir,
           ':ip'     => $ipAddress,
           ':feed'   => $aiFeedUrl,
           ':model'  => $aiModel,
           ':inside' => $aiInside,
           ':ai'     => $isAiTracker ? 1 : 0,
           ':t'      => $now,
           ':d'      => $deviceId,
       ]);
} else {
    $db->prepare('INSERT INTO devices (device_id, gate_name, direction, ip_address, ai_feed_url, ai_model, ai_inside, ai_enabled, last_seen)
                  VALUES (:d, :g, :dir, :ip, :feed, :model, :inside, :ai, :t)')
       ->execute([
           ':d'      => $deviceId,
           ':g'      => ($gateName !== '' ? $gateName : $deviceId),
           ':dir'    => ($deviceDirection !== '' ? $deviceDirection : $direction),
           ':ip'     => $ipAddress,
           ':feed'   => $aiFeedUrl,
           ':model'  => $aiModel,
           ':inside' => ($aiInside === null ? 0 : $aiInside),
           ':ai'     => $isAiTracker ? 1 : 0,
           ':t'      => $now,
       ]);
}

// Only store an event when people were actually counted
if ($count > 0) {
    $eventDir = in_array($direction, ['entry', 'exit'], true) ? $direction : 'entry';
    $db->prepare('INSERT INTO events (device_id, direction, count, created_at) VALUES (:d, :dir, :c, :t)')
       ->execute([':d' => $deviceId, ':dir' => $eventDir, ':c' => $count, ':t' => $now]);
}

$db->commit();

json_response([
    'ok'      => true,
    'message' => 'Reading saved',
    'device'  => $deviceId,
    'ip'      => $ipAddress,
    'time'    => $now
]);
