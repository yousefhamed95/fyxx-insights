<?php
// Fyxx Executive Insights — hosted edition (PHP 7.3 compatible).
// Exact port of the Streamlit dashboard. Session password gate below.

// SameSite=None; Secure lets the session cookie survive when the dashboard
// is embedded in the portal's cross-origin iframe (huggingface space).
// Falls back gracefully for direct (first-party) access.
session_set_cookie_params([
    'lifetime' => 0,
    'path'     => '/',
    'secure'   => true,
    'httponly' => true,
    'samesite' => 'None',
]);
session_start();

define('FYXX_PASSWORD', '2525');

if (isset($_GET['logout'])) {
    unset($_SESSION['fyxx_auth']);
    header('Location: ./');
    exit;
}

$err = '';
if (isset($_POST['pw'])) {
    if (hash_equals(FYXX_PASSWORD, (string)$_POST['pw'])) {
        $_SESSION['fyxx_auth'] = 1;
        header('Location: ./');
        exit;
    }
    $err = 'Wrong password — try again.';
}

$authed = isset($_SESSION['fyxx_auth']) && $_SESSION['fyxx_auth'] === 1;

// --- lightweight live-viewer counter (files touched in last 90s) ---
$viewers = 1;
if ($authed) {
    $vdir = sys_get_temp_dir() . '/fyxx_viewers';
    if (!is_dir($vdir)) { @mkdir($vdir, 0700); }
    @touch($vdir . '/' . session_id());
    $viewers = 0;
    foreach ((array)@scandir($vdir) as $f) {
        if ($f === '.' || $f === '..') continue;
        $p = $vdir . '/' . $f;
        if (@filemtime($p) >= time() - 90) { $viewers++; }
        elseif (@filemtime($p) < time() - 3600) { @unlink($p); }
    }
    if ($viewers < 1) { $viewers = 1; }
}
?>
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Fyxx Executive Insights</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
<link rel="stylesheet" href="streamlit-port.css?v=5">
<link rel="stylesheet" href="style.css?v=5">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>&#128202;</text></svg>">
</head>
<body>
<?php if (!$authed): ?>
<div class="login-wrap">
  <form class="login" method="post" action="./">
    <div class="tag">Fyxx</div>
    <h1>Executive Insights</h1>
    <input type="password" name="pw" placeholder="Password"
           inputmode="numeric" pattern="[0-9]*"
           autofocus autocomplete="current-password">
    <button type="submit">Enter dashboard</button>
    <?php if ($err): ?><div class="err"><?php echo htmlspecialchars($err); ?></div><?php endif; ?>
  </form>
</div>
<?php else: ?>
<div id="loading"><div class="spinner"></div><div class="msg">Loading multi-year sales history…</div></div>

<div class="layout">
  <main class="main">
    <div class="topbar">
      <div class="brand-head">
        <span class="brand-name">Fyxx</span>
        <span class="brand-sub">Executive Insights</span>
      </div>
      <div class="topbar-right">
        <span id="lastupd" class="sync-note">–</span>
        <button class="btn" onclick="location.reload()">↻ Refresh</button>
        <a class="btn btn-danger" href="./?logout=1">Logout</a>
      </div>
    </div>
    <div id="tickerSlot"></div>

    <div class="flabel" style="margin-top:2px">Period</div>
    <div class="pills" id="scopePills"></div>
    <div class="dates" id="customDates">
      <input type="date" id="dFrom"> <span style="color:var(--muted)">→</span>
      <input type="date" id="dTo">
      <button class="btn" id="dApply">Apply</button>
    </div>

    <div class="flabel" style="margin-top:14px">Channels</div>
    <div class="pills" id="chPills"></div>

    <div style="height:1px;background:#1F1F26;margin:18px 0 14px 0"></div>

    <div id="scopeStrip"></div>

    <div class="kpi-grid kpi-strip-main" id="kpis" style="margin-top:18px"></div>

    <div class="tabs" id="tabs"></div>

    <div class="panel" id="p-brief"></div>
    <div class="panel" id="p-exec"></div>
    <div class="panel" id="p-shifts"></div>
    <div class="panel" id="p-pace"></div>
    <div class="panel" id="p-profit"></div>
    <div class="panel" id="p-pnl"></div>
    <div class="panel" id="p-sku"></div>
    <div class="panel" id="p-loss"></div>
    <div class="panel" id="p-alerts"></div>
    <div class="panel" id="p-trends"></div>
    <div class="panel" id="p-channels"></div>
    <div class="panel" id="p-customers"></div>
    <div class="panel" id="p-cohorts"></div>
    <div class="panel" id="p-compare"></div>
    <div class="panel" id="p-live"></div>

    <div class="footer" id="footer"></div>
  </main>
</div>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js" charset="utf-8"></script>
<script src="app.js?v=5"></script>
<script src="tabs2.js?v=5"></script>
<?php endif; ?>
</body>
</html>
