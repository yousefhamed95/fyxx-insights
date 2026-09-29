<?php
// Role-based data scoping for the Fyxx dashboard.
//
// Every login has a role. 'admin' sees everything; 'ecom' (the e-commerce
// manager) sees E-com only. The restriction is enforced HERE, on the server:
// data.php and live.php strip every non-allowed row — and rebuild the
// customer / salesperson / product lists — before anything reaches the
// browser, so a restricted login cannot recover other channels' data by
// inspecting the page or calling the endpoints directly.
if (basename(isset($_SERVER['SCRIPT_FILENAME']) ? $_SERVER['SCRIPT_FILENAME'] : '') === 'role_filter.php') {
    http_response_code(403);
    exit;
}

// role => allowed channels (null = all channels)
function fyxx_role_channels($role) {
    $map = array(
        'admin' => null,
        'ecom'  => array('E-com'),
    );
    // an unknown role sees nothing
    return array_key_exists($role, $map) ? $map[$role] : array();
}

function fyxx_role() {
    // sessions from before roles existed logged in with the admin password
    return isset($_SESSION['fyxx_role']) ? (string)$_SESSION['fyxx_role'] : 'admin';
}

// keep only rows $keep (list of indexes) of the given columns
function fyxx_keep($d, $cols, $keep) {
    $out = $d;
    foreach ($cols as $c) {
        if (!isset($d[$c]) || !is_array($d[$c])) continue;
        $src = $d[$c];
        $col = array();
        foreach ($keep as $i) { $col[] = $src[$i]; }
        $out[$c] = $col;
    }
    return $out;
}

// rebuild a dictionary so it only contains values still referenced
function fyxx_reintern(&$d, $col, $dict) {
    if (!isset($d[$col]) || !isset($d[$dict])) return;
    $old = $d[$dict];
    $map = array();
    $new = array();
    foreach ($d[$col] as $k => $idx) {
        if (!array_key_exists($idx, $map)) {
            $map[$idx] = count($new);
            $new[] = isset($old[$idx]) ? $old[$idx] : null;
        }
        $d[$col][$k] = $map[$idx];
    }
    $d[$dict] = $new;
}

function fyxx_rows_in_channels($d, $allowed) {
    $keep = array();
    $names = isset($d['channels']) ? $d['channels'] : array();
    foreach ($d['ch'] as $i => $ci) {
        if (isset($names[$ci]) && in_array($names[$ci], $allowed, true)) { $keep[] = $i; }
    }
    return $keep;
}

// orders.json (and live.php output, which has the same shape)
function fyxx_filter_orders($d, $allowed) {
    $keep = fyxx_rows_in_channels($d, $allowed);
    $d = fyxx_keep($d, array('ts', 'ch', 'cu', 'sp', 'amt', 'vat', 'mg', 'src', 'nm', 'oid', 'st'), $keep);
    fyxx_reintern($d, 'ch', 'channels');
    fyxx_reintern($d, 'cu', 'customers');
    fyxx_reintern($d, 'sp', 'salespeople');
    fyxx_reintern($d, 'st', 'states');
    if (isset($d['count'])) { $d['count'] = count($d['ts']); }
    return $d;
}

function fyxx_filter_sostates($d, $allowed) {
    $keep = fyxx_rows_in_channels($d, $allowed);
    $d = fyxx_keep($d, array('ts', 'ch', 'st'), $keep);
    fyxx_reintern($d, 'ch', 'channels');
    return $d;
}

function fyxx_filter_delivery($d, $allowed) {
    $keep = fyxx_rows_in_channels($d, $allowed);
    $d = fyxx_keep($d, array('ots', 'dts', 'st', 'car', 'ch'), $keep);
    fyxx_reintern($d, 'ch', 'channels');
    fyxx_reintern($d, 'car', 'carriers');
    return $d;
}

// lines.json: keep lines that belong to an order the role may see
function fyxx_filter_lines($d, $orders_filtered) {
    $ok = array();
    foreach ($orders_filtered['oid'] as $i => $oid) {
        $ok[$orders_filtered['src'][$i] . ':' . $oid] = true;
    }
    $keep = array();
    foreach ($d['oid'] as $i => $oid) {
        if (isset($ok[$d['src'][$i] . ':' . $oid])) { $keep[] = $i; }
    }
    $d = fyxx_keep($d, array('src', 'oid', 'p', 'q', 'r', 'g'), $keep);
    fyxx_reintern($d, 'p', 'products');
    return $d;
}
