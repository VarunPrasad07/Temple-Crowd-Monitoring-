<?php
// Opens the SQLite database and creates the tables if they do not exist.

require_once __DIR__ . '/helpers.php';

function get_db(): PDO
{
    static $pdo = null;
    if ($pdo !== null) {
        return $pdo;
    }

    $path = config()['db_path'];
    $dir  = dirname($path);
    if (!is_dir($dir)) {
        mkdir($dir, 0775, true);
    }

    $pdo = new PDO('sqlite:' . $path);
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    $pdo->setAttribute(PDO::ATTR_DEFAULT_FETCH_MODE, PDO::FETCH_ASSOC);

    // One row per ESP32-CAM device
    $pdo->exec('CREATE TABLE IF NOT EXISTS devices (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        device_id  TEXT NOT NULL UNIQUE,
        gate_name  TEXT NOT NULL,
        direction  TEXT NOT NULL,
        ip_address TEXT DEFAULT "",
        last_seen  TEXT NOT NULL
    )');

    // Ensure ip_address column exists for existing databases
    try {
        $pdo->exec('ALTER TABLE devices ADD COLUMN ip_address TEXT DEFAULT ""');
    } catch (Throwable $e) {
        // Column already exists
    }

    // Columns added by the AI (YOLO) tracker bridge
    $aiColumns = [
        'ai_feed_url' => 'TEXT DEFAULT ""',   // annotated MJPEG preview served by the tracker
        'ai_inside'   => 'INTEGER DEFAULT 0', // live "people inside" reported by the tracker
        'ai_model'    => 'TEXT DEFAULT ""',   // detection model in use, e.g. yolov8n.pt
        'ai_enabled'  => 'INTEGER DEFAULT 0', // 1 = the AI tracker counts this camera
    ];
    foreach ($aiColumns as $column => $definition) {
        try {
            $pdo->exec("ALTER TABLE devices ADD COLUMN {$column} {$definition}");
        } catch (Throwable $e) {
            // Column already exists
        }
    }

    // One row per reading that contained people
    $pdo->exec('CREATE TABLE IF NOT EXISTS events (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        device_id  TEXT NOT NULL,
        direction  TEXT NOT NULL,
        count      INTEGER NOT NULL,
        created_at TEXT NOT NULL
    )');

    $pdo->exec('CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at)');
    $pdo->exec('CREATE INDEX IF NOT EXISTS idx_events_device ON events(device_id, direction)');

    return $pdo;
}
