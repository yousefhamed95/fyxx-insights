<?php
// Auth-gated data endpoint: serves the exporter's JSON files only to a
// logged-in session. Direct HTTP access to data/*.json is blocked by
// data/.htaccess — this proxy is the only way in.
session_start();
if (!isset($_SESSION['fyxx_auth']) || $_SESSION['fyxx_auth'] !== 1) {
    http_response_code(401);
    header('Content-Type: application/json');
    echo '{"error":"unauthorized"}';
    exit;
}

$allowed = array('orders', 'sostates', 'delivery', 'products', 'pnl', 'meta');
$f = isset($_GET['f']) ? (string)$_GET['f'] : '';
if (!in_array($f, $allowed, true)) {
    http_response_code(400);
    header('Content-Type: application/json');
    echo '{"error":"bad file"}';
    exit;
}

$path = __DIR__ . '/data/' . $f . '.json';
if (!is_file($path)) {
    http_response_code(404);
    header('Content-Type: application/json');
    echo '{"error":"not generated yet"}';
    exit;
}

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-cache');
// gzip if the client supports it and the extension is available
if (function_exists('ob_gzhandler')) { ob_start('ob_gzhandler'); }
readfile($path);
