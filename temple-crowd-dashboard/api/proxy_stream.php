<?php
/**
 * api/proxy_stream.php
 * --------------------
 * Transparently proxies an MJPEG stream (or any HTTP resource) from the
 * camera IP through the dashboard server, so the browser loads it from the
 * same origin (http://127.0.0.1:8000) and avoids CORS / mixed-content blocks.
 *
 * Usage:
 *   <img src="api/proxy_stream.php?url=http%3A%2F%2F192.168.1.105%3A81%2Fstream">
 *
 * The JS in app.js rewrites camera stream URLs to go through this proxy
 * when the raw URL is on a different host.
 */

// Allow access from any origin (e.g. when the dashboard is served via LAN IP)
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: GET, OPTIONS');
if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') {
    http_response_code(204);
    exit;
}

$raw = trim($_GET['url'] ?? '');
if ($raw === '') {
    http_response_code(400);
    echo json_encode(['ok' => false, 'error' => 'url parameter required']);
    exit;
}

// Only allow http(s) targets - block file:// etc.
if (!preg_match('#^https?://#i', $raw)) {
    http_response_code(400);
    echo json_encode(['ok' => false, 'error' => 'Only http/https URLs are allowed']);
    exit;
}

// Open a streaming connection to the camera
$ctx = stream_context_create([
    'http' => [
        'timeout'  => 10,
        'method'   => 'GET',
        'header'   => "Connection: keep-alive\r\n",
        'ignore_errors' => true,
    ],
]);

$fp = @fopen($raw, 'rb', false, $ctx);
if ($fp === false) {
    http_response_code(502);
    header('Content-Type: application/json');
    echo json_encode(['ok' => false, 'error' => "Could not connect to stream: $raw"]);
    exit;
}

// Mirror the Content-Type from the upstream response
$meta = stream_get_meta_data($fp);
$contentType = 'application/octet-stream';
if (!empty($meta['wrapper_data'])) {
    foreach ($meta['wrapper_data'] as $h) {
        if (stripos($h, 'content-type:') === 0) {
            $contentType = trim(substr($h, strlen('content-type:')));
            break;
        }
    }
}
header('Content-Type: ' . $contentType);
header('Cache-Control: no-store, no-cache, must-revalidate');
header('Pragma: no-cache');

// Stream bytes to the browser in chunks
if (ob_get_level()) ob_end_clean();
set_time_limit(0);

while (!feof($fp) && !connection_aborted()) {
    $chunk = fread($fp, 8192);
    if ($chunk === false || $chunk === '') break;
    echo $chunk;
    flush();
}

fclose($fp);
