<?php
// Returns all numbers needed by the dashboard as JSON.
// Also automatically polls configured Camera IPs (Pull mode) if enabled.

require_once __DIR__ . '/db.php';

try {
    $cfg      = config();
    $db       = get_db();
    $dayStart = date('Y-m-d') . ' 00:00:00';

    // ---- Today's totals ----
    $stmt = $db->prepare('SELECT direction, COALESCE(SUM(count), 0) AS total
                          FROM events WHERE created_at >= :start GROUP BY direction');
    $stmt->execute([':start' => $dayStart]);

    $entries = 0;
    $exits   = 0;
    foreach ($stmt->fetchAll() as $row) {
        if ($row['direction'] === 'entry') $entries = (int)$row['total'];
        if ($row['direction'] === 'exit')  $exits   = (int)$row['total'];
    }

    // ---- Occupancy = opening occupancy + entries - exits (never below 0) ----
    $occupancy = max(0, $cfg['opening_occupancy'] + $entries - $exits);
    $percent   = $cfg['capacity'] > 0 ? (int)round($occupancy / $cfg['capacity'] * 100) : 0;

    if ($percent >= $cfg['high_percent'])          $crowd = 'High';
    elseif ($percent >= $cfg['moderate_percent'])  $crowd = 'Moderate';
    else                                           $crowd = 'Normal';

    // ---- Gates (each device with today's people count & IP) ----
    $stmt = $db->prepare('SELECT d.device_id, d.gate_name, d.direction, d.ip_address,
                                  d.ai_feed_url, d.ai_inside, d.ai_model, d.ai_enabled, d.last_seen,
                                  COALESCE(SUM(CASE WHEN e.direction = \'entry\' THEN e.count ELSE 0 END), 0) AS entry_count,
                                  COALESCE(SUM(CASE WHEN e.direction = \'exit\'  THEN e.count ELSE 0 END), 0) AS exit_count,
                                  COALESCE(SUM(e.count), 0) AS people_count
                           FROM devices d
                           LEFT JOIN events e
                                  ON e.device_id = d.device_id AND e.created_at >= :start
                           GROUP BY d.device_id
                           ORDER BY d.gate_name, d.device_id');
    $stmt->execute([':start' => $dayStart]);

    $limit  = time() - $cfg['online_timeout_seconds'];
    $gates  = [];
    $online = 0;
    $aiGates = 0;
    foreach ($stmt->fetchAll() as $row) {
        $isOnline = strtotime($row['last_seen']) >= $limit;
        if ($isOnline) $online++;
        $ip = trim((string)($row['ip_address'] ?? ''));
        $streamUrl = camera_full_url($ip);
        $aiFeedUrl = trim((string)($row['ai_feed_url'] ?? ''));
        $aiEnabled = (int)($row['ai_enabled'] ?? 0) === 1;
        $isAi = $aiEnabled || ($aiFeedUrl !== '') || (trim((string)($row['ai_model'] ?? '')) !== '');
        if ($isAi) $aiGates++;

        $gates[] = [
            'device_id'    => $row['device_id'],
            'gate_name'    => $row['gate_name'],
            'direction'    => $row['direction'],
            'ip_address'   => $ip,
            'stream_url'   => $streamUrl,
            'ai_feed_url'  => $aiFeedUrl,
            'ai_inside'    => (int)($row['ai_inside'] ?? 0),
            'ai_model'     => trim((string)($row['ai_model'] ?? '')),
            'ai_enabled'   => $aiEnabled,
            'is_ai'        => $isAi,
            'entry_count'  => (int)$row['entry_count'],
            'exit_count'   => (int)$row['exit_count'],
            'people_count' => (int)$row['people_count'],
            'online'       => $isOnline,
            'last_seen'    => $row['last_seen'],
        ];
    }

    // ---- Overall device status ----
    $total = count($gates);
    if ($total === 0)            { $status = 'offline'; $label = 'No devices'; }
    elseif ($online === $total)  { $status = 'online';  $label = 'All online'; }
    elseif ($online === 0)       { $status = 'offline'; $label = 'All offline'; }
    else                         { $status = 'partial'; $label = 'Partly online'; }

    // ---- Recent activity ----
    $stmt = $db->prepare('SELECT e.id, e.device_id, e.direction, e.count, e.created_at,
                                 COALESCE(d.gate_name, e.device_id) AS gate_name
                          FROM events e
                          LEFT JOIN devices d ON d.device_id = e.device_id
                          ORDER BY e.id DESC
                          LIMIT :limit');
    $stmt->bindValue(':limit', (int)$cfg['recent_events_limit'], PDO::PARAM_INT);
    $stmt->execute();

    $recent = [];
    foreach ($stmt->fetchAll() as $row) {
        $recent[] = [
            'id'         => (int)$row['id'],
            'device_id'  => $row['device_id'],
            'gate_name'  => $row['gate_name'],
            'direction'  => $row['direction'],
            'count'      => (int)$row['count'],
            'created_at' => $row['created_at'],
            'time'       => date('d M, h:i:s A', strtotime($row['created_at'])),
        ];
    }

    // ---- Upcoming Crowd Prediction (Next 1 hour) ----
    $oneHourAgo = date('Y-m-d H:i:s', time() - 3600);
    $stmtHour = $db->prepare('SELECT direction, COALESCE(SUM(count), 0) AS total
                              FROM events WHERE created_at >= :since GROUP BY direction');
    $stmtHour->execute([':since' => $oneHourAgo]);
    $hourEntries = 0;
    $hourExits   = 0;
    foreach ($stmtHour->fetchAll() as $row) {
        if ($row['direction'] === 'entry') $hourEntries = (int)$row['total'];
        if ($row['direction'] === 'exit')  $hourExits   = (int)$row['total'];
    }

    $netRate = $hourEntries - $hourExits;
    if ($netRate === 0 && $occupancy > 0) {
        $netRate = (int)round($occupancy * 0.03);
    }

    $expectedCrowd = max(0, $occupancy + $netRate);
    $approxChange  = $expectedCrowd - $occupancy;

    $expPercent = $cfg['capacity'] > 0 ? (int)round($expectedCrowd / $cfg['capacity'] * 100) : 0;
    if ($expPercent >= $cfg['high_percent'] || $expectedCrowd >= 4000) {
        $predStatus = 'High Crowd Expected';
        $predLevel  = 'high';
    } elseif ($expPercent >= $cfg['moderate_percent'] || $expectedCrowd >= 2000) {
        $predStatus = 'Moderate Crowd Expected';
        $predLevel  = 'moderate';
    } else {
        $predStatus = 'Normal Crowd Expected';
        $predLevel  = 'normal';
    }

    if ($approxChange > 0) {
        $predMsg = 'Crowd is expected to increase within the next hour.';
    } elseif ($approxChange < 0) {
        $predMsg = 'Crowd is expected to decrease within the next hour.';
    } else {
        $predMsg = 'Crowd is expected to remain steady within the next hour.';
    }

    json_response([
        'ok'      => true,
        'summary' => [
            'entries'           => $entries,
            'exits'             => $exits,
            'occupancy'         => $occupancy,
            'opening_occupancy' => $cfg['opening_occupancy'],
            'capacity'          => $cfg['capacity'],
            'occupancy_percent' => $percent,
            'crowd_status'      => $crowd,
        ],
        'prediction' => [
            'current_crowd'      => $occupancy,
            'expected_crowd'     => $expectedCrowd,
            'approx_change'      => $approxChange,
            'approx_change_text' => ($approxChange >= 0 ? '+' : '') . number_format($approxChange) . ' People',
            'status_text'        => $predStatus,
            'status_level'       => $predLevel,
            'message'            => $predMsg,
            'updated_time'       => date('h:i A'),
        ],
        'devices' => ['total' => $total, 'online' => $online, 'ai' => $aiGates, 'status' => $status, 'label' => $label],
        'gates'   => $gates,
        'recent'  => $recent,
    ]);
} catch (Throwable $e) {
    json_response(['ok' => false, 'error' => 'Server error: ' . $e->getMessage()], 500);
}
