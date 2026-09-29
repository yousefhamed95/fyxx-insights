<?php
// Auth-gated data endpoint: serves the exporter's JSON files only to a
// logged-in session. Direct HTTP access to data/*.json is blocked by
// data/.htaccess — this proxy is the only way in.
//
// Role scoping (role_filter.php): the admin login gets the full files; a
// restricted login (e.g. the e-commerce manager) gets copies with every
// other channel removed — rows AND the customer/product lists — so the
// restriction holds even if someone calls this endpoint directly.
session_set_cookie_params([
    'lifetime' => 0, 'path' => '/', 'secure' => true,
    'httponly' => true, 'samesite' => 'None',
]);
session_start();
if (!isset($_SESSION['fyxx_auth']) || $_SESSION['fyxx_auth'] !== 1) {
    http_response_code(401);
    header('Content-Type: application/json');
    echo '{"error":"unauthorized"}';
    exit;
}
require __DIR__ . '/role_filter.php';

$allowed = array('orders', 'sostates', 'delivery', 'lines', 'pnl', 'meta');
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

$role = fyxx_role();
$chans = fyxx_role_channels($role);

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-cache, private');
// gzip if the client supports it and the extension is available
if (function_exists('ob_gzhandler')) { ob_start('ob_gzhandler'); }

if ($chans === null) {          // admin: the full file, unchanged
    readfile($path);
    exit;
}

// Restricted role: a filtered copy, cached per role until the data changes.
$ordersPath = __DIR__ . '/data/orders.json';
$cacheDir = __DIR__ . '/data/cache_' . preg_replace('/[^a-z0-9_]/', '', $role);
$cache = $cacheDir . '/' . $f . '.json';
$srcTime = max(filemtime($path), is_file($ordersPath) ? filemtime($ordersPath) : 0);
if (is_file($cache) && filemtime($cache) >= $srcTime) {
    readfile($cache);
    exit;
}

ini_set('memory_limit', '384M');
ini_set('serialize_precision', '-1');
$d = json_decode(file_get_contents($path), true);
if (!is_array($d)) {
    http_response_code(500);
    echo '{"error":"bad source"}';
    exit;
}
switch ($f) {
    case 'orders':
        $out = fyxx_filter_orders($d, $chans);
        break;
    case 'sostates':
        $out = fyxx_filter_sostates($d, $chans);
        break;
    case 'delivery':
        $out = fyxx_filter_delivery($d, $chans);
        break;
    case 'lines':
        $o = json_decode(file_get_contents($ordersPath), true);
        $out = fyxx_filter_lines($d, fyxx_filter_orders($o, $chans));
        break;
    case 'pnl':
        // company-wide accounts, not channel-attributable: not shown to
        // restricted roles at all
        $out = array('rows' => array(), 'accounts' => array());
        break;
    default:   // meta
        $o = json_decode(file_get_contents($ordersPath), true);
        $out = $d;
        $out['orders'] = count(fyxx_filter_orders($o, $chans)['ts']);
}

$json = json_encode($out, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
if ($json === false) {
    http_response_code(500);
    echo '{"error":"encode failed"}';
    exit;
}
if (!is_dir($cacheDir)) { @mkdir($cacheDir, 0755); }
$tmp = $cache . '.tmp' . getmypid();
if (@file_put_contents($tmp, $json) !== false) { @rename($tmp, $cache); }
echo $json;
