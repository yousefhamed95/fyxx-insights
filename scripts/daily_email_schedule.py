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
  * Exactly one email per report day: right before sending, a run claims the
    day by pushing the git tag "sent-<kind>-<date>". Git refuses to create a
    tag that already exists, atomically, on GitHub's side — so however many
    runs start, only the first can claim the day and every other run skips.
    (The earlier approach asked GitHub's API "did a run already succeed?";
    that answer lagged at times and let duplicate emails through.) If
    building or sending fails, the claim is released so a later run retries;
    if the claim itself can't be made, the run fails loudly instead of risking
    a duplicate.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
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


def tag_name(kind, report_day):
    return f"sent-{kind}-{report_day:%Y-%m-%d}"


def _git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True,
                          timeout=90)


def is_claimed(kind, report_day):
    """True if the day's tag exists on GitHub (read live, no API index)."""
    tag = tag_name(kind, report_day)
    r = _git("ls-remote", "--tags", "origin", f"refs/tags/{tag}")
    if r.returncode != 0:
        raise RuntimeError(f"git ls-remote failed: {r.stderr.strip()}")
    return bool(r.stdout.strip())


def claim(kind, report_day, attempts=3):
    """Atomically claim the right to send this report. Returns True if this
    run holds the claim, False if another run already has it. Raises if
    neither can be established (so the job fails instead of double-sending).

    The tag is ANNOTATED with this run's id and time, so its object is unique:
    pushing it can never be a silent no-op "already up to date" — if the tag
    exists, GitHub rejects the push.
    """
    tag = tag_name(kind, report_day)
    run = os.environ.get("GITHUB_RUN_ID", "local")
    last_err = ""
    for i in range(attempts):
        try:
            if is_claimed(kind, report_day):
                print(f"{tag} is already claimed - this report went out; skipping.")
                return False
        except RuntimeError as e:
            last_err = str(e)
        _git("tag", "-d", tag)                  # drop any stale local copy
        made = _git("-c", "user.name=github-actions[bot]",
                    "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com",
                    "tag", "-a", tag, "-m",
                    f"{tag} claimed by run {run} at {datetime.now(TZ):%Y-%m-%d %H:%M:%S} Amman")
        if made.returncode != 0:
            last_err = made.stderr.strip()
        else:
            pushed = _git("push", "origin", f"refs/tags/{tag}")
            if pushed.returncode == 0:
                print(f"Claimed {tag} - this run sends the email.")
                return True
            last_err = pushed.stderr.strip()
        time.sleep(5 * (i + 1))
    # The push kept failing. If that's because someone else holds the tag,
    # skip; otherwise stop loudly rather than risk a duplicate.
    try:
        if is_claimed(kind, report_day):
            print(f"{tag} was claimed by another run - skipping.")
            return False
    except RuntimeError as e:
        last_err = str(e)
    raise RuntimeError(f"could not claim {tag}: {last_err}")


def release(kind, report_day):
    """Give the claim back after a failed build/send so a later run retries."""
    tag = tag_name(kind, report_day)
    r = _git("push", "origin", f":refs/tags/{tag}")
    print(f"Released {tag}." if r.returncode == 0
          else f"WARN: could not release {tag}: {r.stderr.strip()}")


def cleanup(kind, keep_days=14):
    """Delete this email's claim tags older than keep_days. Never fatal."""
    prefix = f"sent-{kind}-"
    try:
        r = _git("ls-remote", "--tags", "origin", f"refs/tags/{prefix}*")
        cutoff = datetime.now(TZ).date() - timedelta(days=keep_days)
        old = []
        for line in r.stdout.splitlines():
            ref = line.split("\t")[-1]
            if ref.endswith("^{}"):
                continue
            try:
                d = datetime.strptime(ref.rsplit("/", 1)[-1][len(prefix):],
                                      "%Y-%m-%d").date()
            except ValueError:
                continue
            if d < cutoff:
                old.append(f":{ref}")
        if old:
            _git("push", "origin", *old)
            print(f"Removed {len(old)} old claim tag(s).")
    except Exception as e:
        print(f"WARN: tag cleanup skipped ({e})")


def _hold_until(target):
    while True:
        remaining = (target - datetime.now(TZ)).total_seconds()
        if remaining <= 0:
            return
        print(f"  ... holding, {remaining / 60:.0f} min to "
              f"{target:%H:%M} Amman", flush=True)
        time.sleep(min(600.0, remaining))


def gate(kind):
    """For a scheduled run: return the report day this run has CLAIMED and
    must send (after holding until SEND_AT), or None to do nothing."""
    send_at = send_at_setting()
    now = datetime.now(TZ)
    action, report_day, hold = decide(now, send_at)
    print(f"Scheduled run started {now:%Y-%m-%d %H:%M} Amman; "
          f"send time {send_at:%H:%M}.")
    if action == "exit_early":
        print("Outside the sending window for the next report - nothing to do.")
        return None
    if report_day <= LEGACY_SENT_THROUGH:
        print(f"{report_day} was sent by the previous scheduler - skipping.")
        return None
    try:
        if is_claimed(kind, report_day):     # cheap check before a long hold
            print(f"{tag_name(kind, report_day)} already claimed - skipping.")
            return None
    except RuntimeError as e:
        print(f"WARN: {e} (will rely on the atomic claim)")
    if hold > 0:
        target = now + timedelta(seconds=hold)
        print(f"Report for {report_day}: holding {hold / 60:.0f} min "
              f"until {target:%H:%M} Amman.", flush=True)
        _hold_until(target)
    return report_day if claim(kind, report_day) else None
