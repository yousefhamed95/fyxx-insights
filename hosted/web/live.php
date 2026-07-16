<?php
/**
 * Live tail endpoint — queries Odoo (read-only, JSON-RPC) for TODAY's orders
 * on every call, so the dashboard's Today/Live/MTD views are genuinely live
 * instead of frozen at the last snapshot sync.
 *
 * Returns the same columnar shape as orders.json, covering the current
 * Amman-local day. The front-end overlays this over the snapshot's "today".
 *
 * Session-gated like data.php. Odoo credentials live in odoo_config.php
 * (a PHP file, never served as source).
 */
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

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

$cfg = @include __DIR__ . '/odoo_config.php';
if (!is_array($cfg) || empty($cfg['ODOO_URL'])) {
    echo json_encode(['error' => 'no odoo config']);
    exit;
}

$URL = rtrim($cfg['ODOO_URL'], '/');
$DB  = $cfg['ODOO_DB'];
$LOGIN = $cfg['ODOO_LOGIN'];
$KEY = $cfg['ODOO_API_KEY'];

/* ---- JSON-RPC helper ---- */
function odoo_rpc($url, $payload) {
    $ch = curl_init($url . '/jsonrpc');
    curl_setopt_array($ch, [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_POST => true,
        CURLOPT_HTTPHEADER => ['Content-Type: application/json'],
        CURLOPT_POSTFIELDS => json_encode($payload),
        CURLOPT_TIMEOUT => 25,
        CURLOPT_SSL_VERIFYPEER => true,
    ]);
    $res = curl_exec($ch);
    if ($res === false) { return ['__err' => curl_error($ch)]; }
    curl_close($ch);
    $j = json_decode($res, true);
    if (isset($j['error'])) { return ['__err' => 'odoo error']; }
    return isset($j['result']) ? $j['result'] : ['__err' => 'no result'];
}
function odoo_kw($url, $db, $uid, $key, $model, $method, $args, $kwargs = []) {
    return odoo_rpc($url, [
        'jsonrpc' => '2.0', 'method' => 'call',
        'params' => [
            'service' => 'object', 'method' => 'execute_kw',
            'args' => [$db, $uid, $key, $model, $method, $args, $kwargs],
        ],
    ]);
}

/* ---- authenticate ---- */
$uid = odoo_rpc($URL, [
    'jsonrpc' => '2.0', 'method' => 'call',
    'params' => ['service' => 'common', 'method' => 'authenticate',
                 'args' => [$DB, $LOGIN, $KEY, new stdClass()]],
]);
if (!is_int($uid)) {
    echo json_encode(['error' => 'auth failed']);
    exit;
}

/* ---- today window (Asia/Amman) -> UTC strings for Odoo ---- */
$tz = new DateTimeZone('Asia/Amman');
$utc = new DateTimeZone('UTC');
$now = new DateTime('now', $tz);
// Window start = the snapshot's day (passed as ?since=YYYY-MM-DD) so the live
// tail auto-covers every recent day the snapshot is missing — no gaps even if
// the snapshot is stale. Falls back to today; capped to 30 days for load.
$since = isset($_GET['since']) ? preg_replace('/[^0-9\-]/', '', $_GET['since']) : '';
$start = DateTime::createFromFormat('Y-m-d', $since, $tz);
if (!$start) { $start = clone $now; }
$start->setTime(0, 0, 0);
$min = (clone $now)->modify('-30 days')->setTime(0, 0, 0);
if ($start < $min) { $start = $min; }
if ($start > $now) { $start = (clone $now)->setTime(0, 0, 0); }
$start_utc = (clone $start)->setTimezone($utc)->format('Y-m-d H:i:s');
$end_utc   = (clone $now)->setTimezone($utc)->format('Y-m-d H:i:s');
$window_start_ts = $start->getTimestamp();

/* ---- business rules (mirror app.py / exporter) ---- */
function resolve_channel_so($sp, $co) {
    $sp = strtolower($sp); $co = strtolower($co);
    if (strpos($co, 'fyxx operations') !== false) {
        if (strpos($sp, 'shopify') !== false) return 'E-com';
        if (strpos($sp, 'tareq') !== false || strpos($sp, 'yousef') !== false) return 'B2B';
    }
    return 'Retail';
}
$POS_MAP = [3 => 'TGR', 2 => 'Retail', 5 => 'Retail', 6 => 'Retail', 7 => 'TGR', 8 => 'TGR'];
function is_excluded($name) {
    $n = strtolower($name);
    return (strpos($n, 'fyxx operations') !== false) || (strpos($n, 'jt international') !== false);
}
function df_override($name) {
    $n = strtolower($name);
    if (strpos($n, 'jordanian duty free') !== false || strpos($n, 'duty free shops') !== false) return 'DF';
    return null;
}
function to_ts($s) {  // Odoo UTC datetime string -> epoch
    return strtotime($s . ' UTC');
}

/* ---- fetch today's confirmed sale.order + pos.order ---- */
$sos = odoo_kw($URL, $DB, $uid, $KEY, 'sale.order', 'search_read',
    [[['date_order', '>=', $start_utc], ['date_order', '<=', $end_utc],
      ['state', 'in', ['sale', 'done']]]],
    ['fields' => ['name', 'partner_id', 'user_id', 'company_id',
                  'amount_untaxed', 'amount_tax', 'date_order', 'margin'],
     'limit' => 100000]);
$poss = odoo_kw($URL, $DB, $uid, $KEY, 'pos.order', 'search_read',
    [[['date_order', '>=', $start_utc], ['date_order', '<=', $end_utc],
      ['state', 'in', ['paid', 'done', 'invoiced']],
      ['config_id', 'not in', [4]]]],
    ['fields' => ['name', 'partner_id', 'user_id', 'config_id',
                  'amount_total', 'amount_tax', 'date_order', 'margin'],
     'limit' => 100000]);
if (isset($sos['__err']) || isset($poss['__err'])) {
    echo json_encode(['error' => 'odoo query failed']);
    exit;
}

/* ---- intern + build columnar output ---- */
$ch_list = []; $ch_ix = [];
$cu_list = []; $cu_ix = [];
$sp_list = []; $sp_ix = [];
$st_list = []; $st_ix = [];
function intern(&$list, &$ix, $s) {
    if ($s === null) $s = '—';
    if (!isset($ix[$s])) { $ix[$s] = count($list); $list[] = $s; }
    return $ix[$s];
}

$ts = []; $ch = []; $cu = []; $sp = []; $amt = []; $vat = []; $mg = [];
$src = []; $nm = []; $oid = []; $st = [];

foreach ($sos as $o) {
    $cust = is_array($o['partner_id']) ? $o['partner_id'][1] : '—';
    if (is_excluded($cust)) continue;
    $sales = is_array($o['user_id']) ? $o['user_id'][1] : '—';
    $comp = is_array($o['company_id']) ? $o['company_id'][1] : '';
    $chan = df_override($cust);
    if ($chan === null) $chan = resolve_channel_so($sales, $comp);
    $ts[]  = to_ts($o['date_order']);
    $ch[]  = intern($ch_list, $ch_ix, $chan);
    $cu[]  = intern($cu_list, $cu_ix, $cust);
    $sp[]  = intern($sp_list, $sp_ix, $sales);
    $amt[] = round(floatval($o['amount_untaxed']), 2);
    $vat[] = round(floatval($o['amount_tax']), 2);
    $mg[]  = round(floatval($o['margin']), 2);
    $src[] = 0;
    $nm[]  = $o['name'];
    $oid[] = $o['id'];
    $st[]  = intern($st_list, $st_ix, 'sale');
}
foreach ($poss as $o) {
    $cid = is_array($o['config_id']) ? $o['config_id'][0] : null;
    $chan = isset($POS_MAP[$cid]) ? $POS_MAP[$cid]
            : (is_array($o['config_id']) ? $o['config_id'][1] : 'POS');
    $cust = is_array($o['partner_id']) ? $o['partner_id'][1] : 'Walk-in';
    if (is_excluded($cust)) continue;
    $ov = df_override($cust);
    if ($ov !== null) $chan = $ov;
    $sales = is_array($o['user_id']) ? $o['user_id'][1] : '—';
    $net = floatval($o['amount_total']) - floatval($o['amount_tax']);
    $ts[]  = to_ts($o['date_order']);
    $ch[]  = intern($ch_list, $ch_ix, $chan);
    $cu[]  = intern($cu_list, $cu_ix, $cust);
    $sp[]  = intern($sp_list, $sp_ix, $sales);
    $amt[] = round($net, 2);
    $vat[] = round(floatval($o['amount_tax']), 2);
    $mg[]  = round(floatval($o['margin']), 2);
    $src[] = 1;
    $nm[]  = $o['name'];
    $oid[] = $o['id'];
    $st[]  = intern($st_list, $st_ix, 'paid');
}

echo json_encode([
    'ts' => $ts, 'ch' => $ch, 'cu' => $cu, 'sp' => $sp,
    'amt' => $amt, 'vat' => $vat, 'mg' => $mg, 'src' => $src,
    'nm' => $nm, 'oid' => $oid, 'st' => $st,
    'channels' => $ch_list, 'customers' => $cu_list,
    'salespeople' => $sp_list, 'states' => $st_list,
    'window_start_ts' => $window_start_ts,
    'today_midnight_ts' => $window_start_ts,   // alias for older front-ends
    'now' => $now->format('Y-m-d H:i:s'),
    'count' => count($ts),
]);
