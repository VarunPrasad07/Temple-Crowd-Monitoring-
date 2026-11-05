<?php
// API endpoint for manually adding, listing, and deleting camera IP devices.
//
// POST: Add or update a camera device with its IP address
// DELETE: Remove a camera device

require_once __DIR__ . '/db.php';

$method = $_SERVER['REQUEST_METHOD'];

// Support DELETE method via query parameter or header if needed
if ($method === 'POST' && isset($_GET['_method']) && strtoupper($_GET['_method']) === 'DELETE') {
    $method = 'DELETE';
}

$db = get_db();

if ($method === 'GET') {
    $stmt = $db->query('SELECT id, device_id, gate_name, direction, ip_address, ai_feed_url, ai_inside, ai_model, ai_enabled, last_seen
                        FROM devices ORDER BY id DESC');
    json_response(['ok' => true, 'devices' => $stmt->fetchAll()]);
}

if ($method === 'POST') {
    $data      = read_json_body();
    $rawIp     = trim((string)($data['ip_address'] ?? ''));
    $gateName  = trim((string)($data['gate_name'] ?? ''));
    $deviceId  = trim((string)($data['device_id'] ?? ''));
    $direction = strtolower(trim((string)($data['direction'] ?? 'entry')));
    $initialCount = isset($data['initial_count']) ? (int)$data['initial_count'] : 0;
    $aiFeedUrl = trim((string)($data['ai_feed_url'] ?? ''));
    $hasAiFlag = array_key_exists('ai_enabled', $data);
    $aiEnabled = $hasAiFlag ? (int)(bool)$data['ai_enabled'] : 0;

    // ---- Quick toggle: enable / disable AI counting for one camera ---- //
    if ($hasAiFlag && $rawIp === '' && $deviceId !== '') {
        $db->prepare('UPDATE devices SET ai_enabled = :ai WHERE device_id = :d')
           ->execute([':ai' => $aiEnabled, ':d' => $deviceId]);
        json_response([
            'ok'      => true,
            'message' => $aiEnabled ? 'AI counting enabled' : 'AI counting disabled',
            'device'  => ['device_id' => $deviceId, 'ai_enabled' => $aiEnabled],
        ]);
    }

    if (!in_array($direction, ['entry', 'exit', 'both'], true)) {
        $direction = 'entry';
    }

    if ($rawIp === '') {
        json_response(['ok' => false, 'error' => 'IP Address or Stream URL is required (e.g. 192.168.137.160:81/stream)'], 400);
    }

    // Clean IP: strip http://, https://, and trailing slashes
    $cleanIp = normalize_camera_url($rawIp);
    if ($cleanIp === '') {
        json_response(['ok' => false, 'error' => 'Invalid camera address'], 400);
    }

    // Auto-generate device_id if omitted
    if ($deviceId === '') {
        $countStmt = $db->query('SELECT COUNT(*) as total FROM devices');
        $num = (int)$countStmt->fetchColumn() + 1;
        $deviceId = 'CAM-' . str_pad($num, 2, '0', STR_PAD_LEFT);
    }

    if ($gateName === '') {
        $gateName = 'Gate ' . $deviceId;
    }

    $now = date('Y-m-d H:i:s');
    $lastSeen = $now; // Mark recently configured

    // Probe the camera so the UI can honestly report whether it is reachable
    $isOnline = camera_is_reachable($cleanIp, 1.5);

    $db->beginTransaction();

    $find = $db->prepare('SELECT id FROM devices WHERE device_id = :d');
    $find->execute([':d' => $deviceId]);

    if ($find->fetch()) {
        $db->prepare("UPDATE devices SET gate_name = :g, direction = :dir, ip_address = :ip,
                                  ai_feed_url = COALESCE(NULLIF(:feed, ''), ai_feed_url),
                                  ai_enabled = CASE WHEN :aiFlag THEN :ai ELSE ai_enabled END,
                                  last_seen = :t
                      WHERE device_id = :d")
           ->execute([
               ':g'      => $gateName,
               ':dir'    => $direction,
               ':ip'     => $cleanIp,
               ':feed'   => $aiFeedUrl,
               ':aiFlag' => $hasAiFlag ? 1 : 0,
               ':ai'     => $aiEnabled,
               ':t'      => $lastSeen,
               ':d'      => $deviceId,
           ]);
    } else {
        $db->prepare('INSERT INTO devices (device_id, gate_name, direction, ip_address, ai_feed_url, ai_enabled, last_seen)
                      VALUES (:d, :g, :dir, :ip, :feed, :ai, :t)')
           ->execute([
               ':d'    => $deviceId,
               ':g'    => $gateName,
               ':dir'  => $direction,
               ':ip'   => $cleanIp,
               ':feed' => $aiFeedUrl,
               ':ai'   => $aiEnabled,
               ':t'    => $lastSeen,
           ]);
    }

    if ($initialCount > 0) {
        $eventDir = in_array($direction, ['entry', 'exit'], true) ? $direction : 'entry';
        $db->prepare('INSERT INTO events (device_id, direction, count, created_at) VALUES (:d, :dir, :c, :t)')
           ->execute([':d' => $deviceId, ':dir' => $eventDir, ':c' => $initialCount, ':t' => $now]);
    }

    $db->commit();

    json_response([
        'ok'      => true,
        'message' => $isOnline ? 'Camera connected & verified online!' : 'Camera added (marked offline until powered on)',
        'online'  => $isOnline,
        'device'  => [
            'device_id'  => $deviceId,
            'gate_name'  => $gateName,
            'direction'  => $direction,
            'ip_address' => $cleanIp,
            'online'     => $isOnline,
        ],
    ]);
}

if ($method === 'DELETE') {
    $data = read_json_body();
    $deviceId = trim((string)($data['device_id'] ?? $_GET['device_id'] ?? ''));

    if ($deviceId === '') {
        json_response(['ok' => false, 'error' => 'device_id is required'], 400);
    }

    $db->beginTransaction();
    $db->prepare('DELETE FROM devices WHERE device_id = :d')->execute([':d' => $deviceId]);
    $db->prepare('DELETE FROM events WHERE device_id = :d')->execute([':d' => $deviceId]);
    $db->commit();

    json_response(['ok' => true, 'message' => "Device {$deviceId} removed"]);
}

json_response(['ok' => false, 'error' => 'Method not allowed'], 405);
