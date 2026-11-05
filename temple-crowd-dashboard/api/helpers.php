<?php
// Small helper functions shared by all API files.

function config(): array
{
    static $config = null;
    if ($config === null) {
        $config = require __DIR__ . '/config.php';
    }
    return $config;
}

function json_response(array $data, int $status = 200): void
{
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    echo json_encode($data);
    exit;
}

function read_json_body(): array
{
    $raw  = file_get_contents('php://input');
    $data = json_decode($raw, true);
    return is_array($data) ? $data : [];
}

/**
 * Normalises a camera address into "host[:port][/path]" form.
 * Accepts "192.168.1.5", "192.168.1.5:81/stream", "http://192.168.1.5/stream".
 */
function normalize_camera_url(string $raw): string
{
    $url = trim($raw);
    if ($url === '') {
        return '';
    }
    $url = preg_replace('#^https?://#i', '', $url);
    return rtrim($url, '/');
}

/** Builds a full http(s) URL from a stored camera address. */
function camera_full_url(string $stored): string
{
    $stored = trim($stored);
    if ($stored === '') {
        return '';
    }
    return preg_match('#^https?://#i', $stored) ? $stored : 'http://' . $stored;
}

/**
 * Quick reachability probe for a camera (used when a camera is added manually).
 * Returns true when the device answers HTTP within the timeout.
 */
function camera_is_reachable(string $rawUrl, float $timeout = 1.5): bool
{
    $url = camera_full_url(normalize_camera_url($rawUrl));
    if ($url === '') {
        return false;
    }

    $context = stream_context_create([
        'http' => [
            'method'          => 'GET',
            'timeout'         => $timeout,
            'ignore_errors'   => true,
            'follow_location' => 0,
            'header'          => "Range: bytes=0-64\r\nConnection: close\r\n",
        ],
    ]);

    $handle = @fopen($url, 'rb', false, $context);
    if ($handle === false) {
        return false;
    }
    $chunk = @fread($handle, 1);
    fclose($handle);
    return $chunk !== false;
}

