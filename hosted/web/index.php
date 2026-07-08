<?php
// Fyxx Executive Insights — hosted edition (PHP 7.3 compatible).
// Simple session password gate; change FYXX_PASSWORD below any time.
session_start();

define('FYXX_PASSWORD', 'Fyxx#Insights2026');

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
<link rel="stylesheet" href="style.css?v=1">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>&#128202;</text></svg>">
</head>
<body>
<?php if (!$authed): ?>
<div class="login-wrap">
  <form class="login" method="post" action="./">
    <div class="tag">Fyxx</div>
    <h1>Executive Insights</h1>
    <input type="password" name="pw" placeholder="Password" autofocus autocomplete="current-password">
    <button type="submit">Enter dashboard</button>
    <?php if ($err): ?><div class="err"><?php echo htmlspecialchars($err); ?></div><?php endif; ?>
  </form>
</div>
<?php else: ?>
<div id="loading"><div class="spinner"></div><div class="msg">Loading Fyxx insights…</div></div>
<div class="wrap">
  <div class="hdr">
    <div class="brand">
      <h1>Fyxx</h1><span class="tag">Executive Insights</span>
    </div>
    <div class="hdr-meta">
      <span id="lastupd">–</span>
      <button class="btn" onclick="location.reload()">↻ Refresh</button>
      <a class="btn btn-danger" href="./?logout=1" style="text-decoration:none">Logout</a>
    </div>
  </div>

  <div class="filters">
    <div class="fgroup">
      <div class="flabel">Period</div>
      <div class="pills" id="scopePills"></div>
    </div>
    <div class="fgroup">
      <div class="flabel">Channels</div>
      <div class="pills" id="chPills"></div>
    </div>
    <div class="fgroup dates" id="customDates">
      <input type="date" id="dFrom"> <span style="color:var(--muted)">→</span>
      <input type="date" id="dTo">
      <button class="btn" id="dApply">Apply</button>
    </div>
  </div>

  <div class="kpi-grid" id="kpis"></div>

  <div class="tabs" id="tabs"></div>

  <div class="panel" id="p-overview"></div>
  <div class="panel" id="p-channels"></div>
  <div class="panel" id="p-customers"></div>
  <div class="panel" id="p-shifts"></div>
  <div class="panel" id="p-products"></div>
  <div class="panel" id="p-pnl"></div>
</div>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js" charset="utf-8"></script>
<script src="app.js?v=1"></script>
<?php endif; ?>
</body>
</html>
