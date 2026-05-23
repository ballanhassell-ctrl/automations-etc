#!/usr/bin/env python3
"""
CaseOh cloud liveness checker (Path 2).

Runs on GitHub Actions, not on your Mac. Polls the Twitch API during the
10pm-11pm America/New_York window and sends a phone push via ntfy the moment
caseoh_ goes live, or a "not live by 11pm" notice at the cutoff.

The workflow is scheduled with two crons (02:05 UTC and 03:05 UTC) so that one
of them lines up with 22:05 America/New_York year-round, regardless of DST.
This script no-ops fast on the wrong-DST run so we never sit idle and burn the
GitHub Actions timeout.

Reads everything from environment variables, which GitHub injects from your
encrypted repository secrets. Nothing sensitive lives in this file.

TWITCH_CLIENT_ID
TWITCH_CLIENT_SECRET
NTFY_TOPIC          your private ntfy topic name
TEST_NOW            set to "true" by a manual run to skip the time gate
"""

import os
import sys
import time
import requests
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo

CHANNEL = "caseoh_"
NY = ZoneInfo("America/New_York")
WINDOW_START = dtime(22, 5)   # 10:05 PM New York, every night
WINDOW_END   = dtime(23, 5)   # 11:05 PM New York
POLL_INTERVAL_SECONDS = 180   # check every 3 minutes
# Safety net. The window is 60 minutes; allow a little slack but stay well
# under the workflow timeout of 70 minutes.
HARD_MAX_RUNTIME_SECONDS = 65 * 60
# How far before WINDOW_START we are willing to sit and wait. If the runner
# fires earlier than this (e.g. the wrong-DST cron), exit cleanly so the other
# cron handles tonight and we never hit the GitHub Actions kill.
MAX_PREWAIT_SECONDS = 15 * 60

CLIENT_ID = os.environ["TWITCH_CLIENT_ID"]
CLIENT_SECRET = os.environ["TWITCH_CLIENT_SECRET"]
NTFY_TOPIC = os.environ["NTFY_TOPIC"]
TEST_NOW = os.environ.get("TEST_NOW", "false").lower() == "true"

def now_ny():
    return datetime.now(NY)

def todays_window_bounds():
    """Return concrete (start_dt, end_dt) datetimes for tonight's window in NY time.

    Anchored on today's date in NY. Using real datetimes (not just time-of-day)
    means the comparisons stay correct even if the runner crosses midnight.
    """
    today = now_ny().date()
    start_dt = datetime.combine(today, WINDOW_START, tzinfo=NY)
    end_dt = datetime.combine(today, WINDOW_END, tzinfo=NY)
    return start_dt, end_dt

def get_token():
    r = requests.post(
        "https://id.twitch.tv/oauth2/token",
        params={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "grant_type": "client_credentials",
        },
        timeout=15,
    )
    r.raise_for_status()
    return r.json()["access_token"]

def is_live(token):
    r = requests.get(
        "https://api.twitch.tv/helix/streams",
        params={"user_login": CHANNEL},
        headers={"Client-Id": CLIENT_ID, "Authorization": f"Bearer {token}"},
        timeout=15,
    )
    r.raise_for_status()
    return len(r.json().get("data", [])) > 0

def push(message, priority="default", tags="purple_heart"):
    """Send an ntfy push. Never raises: if ntfy is down we still want the
    rest of the script to keep going (or exit cleanly), not crash silently."""
    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=message.encode("utf-8"),
            headers={
                "Title": "CaseOh Stream",
                "Priority": priority,
                "Tags": tags,
                "Click": f"https://twitch.tv/{CHANNEL}",
            },
            timeout=15,
        )
    except Exception as e:
        print(f"{now_ny()}: ntfy push failed: {e}")

def main():
    process_start = time.monotonic()
    token = get_token()

    # Manual test run: one check, one notification, done. No waiting.
    if TEST_NOW:
        live = is_live(token)
        push(f"TEST run: caseoh_ live status is {live}.", tags="test_tube")
        print(f"{now_ny()}: TEST run, live={live}")
        return

    start_dt, end_dt = todays_window_bounds()
    now = now_ny()

    # Already past the window for today: skip cleanly.
    if now >= end_dt:
        print(f"{now}: started after window end {end_dt}, exiting.")
        return

    # Too early. This is the wrong-DST cron firing; the other cron will cover
    # tonight. Exit fast so we don't waste the Actions runtime budget.
    seconds_until_start = (start_dt - now).total_seconds()
    if seconds_until_start > MAX_PREWAIT_SECONDS:
        print(
            f"{now}: {int(seconds_until_start)}s until window starts; "
            f"this is the wrong-DST cron, exiting so the other cron handles it."
        )
        return

    # Within the small pre-window slack: wait until the window opens.
    while now_ny() < start_dt:
        time.sleep(15)

    while now_ny() < end_dt:
        # Belt-and-suspenders: never let the script run longer than the
        # safety budget, even if something weird happens with the clock.
        if time.monotonic() - process_start > HARD_MAX_RUNTIME_SECONDS:
            push("Check aborted: hit hard runtime cap before window close.",
                 priority="low", tags="warning")
            print(f"{now_ny()}: hard runtime cap hit, exiting.")
            return
        try:
            if is_live(token):
                push("CaseOh is LIVE. Tap to watch.",
                     priority="high", tags="red_circle,tv")
                print(f"{now_ny()}: live, notified, exiting.")
                return
            print(f"{now_ny()}: not live yet.")
        except Exception as e:
            print(f"{now_ny()}: check failed: {e}")
        time.sleep(POLL_INTERVAL_SECONDS)

    push("CaseOh never went live by 11pm.", priority="low", tags="zzz")
    print(f"{now_ny()}: cutoff reached, not live.")

if __name__ == "__main__":
    main()
