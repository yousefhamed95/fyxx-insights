"""Shared cut-off, send-time and once-per-day control for the Fyxx daily emails.

Business day and cut-off
------------------------
Report day X covers 03:00 on X -> 03:00 on X+1 (Asia/Amman). The cut-off is
03:00 every night, so late-night trade belongs to the day it happened and no
hour is ever counted in two reports. Nothing about day X is final before
03:00 on X+1, so day X is always sent on the morning of X+1.

Why runs are held until the send time
-------------------------------------
GitHub's cron is best-effort; for this repo scheduled runs have been starting
5-6.5 hours late (a "05:00" email was landing around 10:30). To deliver at an
exact time anyway, the workflows are triggered early (evening and small hours)
and a scheduled run is parked here until SEND_AT (Amman) before it sends.

Decision rules for a SCHEDULED run (manual runs are never held or deduped):
  * 20:00-03:00    -> too early for the next report; exit quietly.
  * 03:00-SEND_AT  -> report = yesterday; hold until SEND_AT, then send.
  * SEND_AT-20:00  -> report = yesterday; if it has not gone out yet, send now
                      (late, but never silently skipped).
  * One email per report day: after a scheduled send the workflow uploads a
    small "sent-<kind>-<date>" artifact; later runs look for it and skip.
    The workflows also serialise their runs (concurrency group), so a second
    run can only start after the sender has finished and left its marker.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from datetime import date, datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Amman")
CUTOFF = dtime(3, 0)        # business day ends at 03:00
EVENING = dtime(20, 0)      # runs from here until the cut-off belong to tomorrow
MAX_HOLD = 5.5 * 3600       # stay safely under GitHub's 6-hour job limit

# The previous scheduler already sent every report up to and including this
# day, without leaving the new "sent" markers. Delayed triggers from the old
# schedule may still be queued at GitHub when this change lands, so never
# re-send these days from a scheduled run.
LEGACY_SENT_THROUGH = date(2026, 9, 28)


def business_window(report_day):
    """(start, end) of a business day: 03:00 report_day -> 03:00 next day."""
    start = datetime.combine(report_day, CUTOFF, TZ)
    return start, start + timedelta(days=1)


def is_scheduled():
    return os.environ.get("GITHUB_EVENT_NAME") == "schedule"


def is_dry_run():
    return (os.environ.get("DRY_RUN") or "").strip().lower() == "true"


def send_at_setting():
    raw = (os.environ.get("SEND_AT") or "08:30").strip()
    h, m = (int(x) for x in raw.split(":"))
    return dtime(h, m)


def decide(now_local, send_at):
    """Pure decision for a scheduled run.

    Returns (action, report_day, hold_seconds) where action is
    'exit_early' or 'send'.
    """
    tod = now_local.time()
    if tod >= EVENING or tod < CUTOFF:
        return "exit_early", None, 0.0
    target = now_local.replace(hour=send_at.hour, minute=send_at.minute,
                               second=0, microsecond=0)
    hold = max(0.0, (target - now_local).total_seconds())
    if hold > MAX_HOLD:
        return "exit_early", None, 0.0
    return "send", now_local.date() - timedelta(days=1), hold


def marker_name(kind, report_day):
    return f"sent-{kind}-{report_day:%Y-%m-%d}"


def already_sent(kind, report_day):
    """True if a scheduled run already sent this report (marker artifact).
    Fails open: if GitHub can't be asked, assume it has not been sent."""
    if report_day <= LEGACY_SENT_THROUGH:
        print(f"{report_day} was sent by the previous scheduler - skipping.")
        return True
    repo = os.environ.get("GITHUB_REPOSITORY")
    token = os.environ.get("GITHUB_TOKEN")
    if not (repo and token):
        return False
    name = marker_name(kind, report_day)
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/actions/artifacts"
        f"?name={name}&per_page=5",
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        sys.stderr.write(f"WARN: sent-marker check failed ({e}); "
                         f"assuming not sent\n")
        return False
    found = [a for a in data.get("artifacts", []) if not a.get("expired")]
    if found:
        print(f"{name} already exists - this report went out; skipping.")
    return bool(found)


def _hold_until(target):
    while True:
        remaining = (target - datetime.now(TZ)).total_seconds()
        if remaining <= 0:
            return
        print(f"  ... holding, {remaining / 60:.0f} min to "
              f"{target:%H:%M} Amman", flush=True)
        time.sleep(min(600.0, remaining))


def gate(kind):
    """For a scheduled run: return the report day to send (after holding until
    SEND_AT), or None if this run should do nothing."""
    send_at = send_at_setting()
    now = datetime.now(TZ)
    action, report_day, hold = decide(now, send_at)
    print(f"Scheduled run started {now:%Y-%m-%d %H:%M} Amman; "
          f"send time {send_at:%H:%M}.")
    if action == "exit_early":
        print("Outside the sending window for the next report - nothing to do.")
        return None
    if already_sent(kind, report_day):
        return None
    if hold > 0:
        target = now + timedelta(seconds=hold)
        print(f"Report for {report_day}: holding {hold / 60:.0f} min "
              f"until {target:%H:%M} Amman.", flush=True)
        _hold_until(target)
        if already_sent(kind, report_day):   # belt and braces
            return None
    return report_day


def mark_sent(kind, report_day):
    """Tell the workflow to upload the per-day 'sent' marker."""
    name = marker_name(kind, report_day)
    with open("sent-marker.txt", "w", encoding="utf-8") as fh:
        fh.write(f"{name} sent {datetime.now(TZ):%Y-%m-%d %H:%M:%S} Amman\n")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"sent=true\nmarker={name}\n")
    print(f"Marked {name}.")
