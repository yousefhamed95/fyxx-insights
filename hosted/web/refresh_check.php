<?php
// Host-side lazy snapshot refresh — no GitHub, no cron panel.
// When a logged-in user opens the dashboard and the snapshot is older than the
// threshold (and no refresh is already running), the host regenerates the full
// snapshot in the background via its own Python. The live tail keeps *today*
// real-time; this keeps the full snapshot (history + order lines + P&L +
// delivery) current. Non-blocking — returns immediately.
(function () {
    $dir  = __DIR__ . '/data';
    $meta = $dir . '/meta.json';
    $lock = $dir . '/.refresh.lock';
    $STALE    = 3 * 3600;   // regenerate if the snapshot is older than 3 hours
    $LOCK_TTL = 15 * 60;    // a run started in the last 15 min is still going

    if (!function_exists('shell_exec')) return;
    $age = is_file($meta) ? (time() - filemtime($meta)) : PHP_INT_MAX;
    if ($age < $STALE) return;
    if (is_file($lock) && (time() - filemtime($lock)) < $LOCK_TTL) return;

    @touch($lock);
    $cmd = 'cd ' . escapeshellarg($dir)
         . ' && LOCAL_OUT_DIR=' . escapeshellarg($dir)
         . ' ODOO_CREDS_FILE=' . escapeshellarg($dir . '/odoo_creds.json')
         . ' nohup /usr/bin/python3 fyxx_export.py > '
         . escapeshellarg($dir . '/refresh.log') . ' 2>&1 &';
    @shell_exec($cmd);
})();
