#!/usr/bin/env python3
"""
CaseOh cloud liveness checker (Path 2).

Runs on GitHub Actions, not on your Mac. Polls the Twitch API during the
10pm-11pm America/New_York window and sends a phone push via ntfy the moment
caseoh_ goes live, or a "not live by 11pm" notice at the cutoff.

Reads everything from environment variables, which GitHub injects from your
encrypted repository secrets. Nothing sensitive lives in this file.

  TWITCH_CLIENT_ID
  TWITCH_CLIENT_SECRET
  NTFY_TOPIC           your private ntfy topic name
  TEST_NOW             set to "true" by a manual run to skip the time gate
"""

import os
import sys
import time
import requests
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo

CHANNEL = "caseoh_"
NY = ZoneInfo("America/New_York")
WINDOW_START = dtime(22, 5)   # 10:05 PM New York
WINDOW_END = dtime(23, 5)     # 11:05 PM New York
POLL_INTERVAL_SECONDS = 180   # check every 3 minutes
HARD_MAX_RUNTIME_SECONDS = 80 * 60  # safety net: never run longer than 80 min

CLIENT_ID = os.environ["TWITCH_CLIENT_ID"]
CLIENT_SECRET = os.environ["TWITCH_CLIENT_SECRET"]
NTFY_TOPIC = os.environ["NTFY_TOPIC"]
TEST_NOW = os.environ.get("TEST_NOW", "false").lower() == "true"

def now_ny():
    return datetime.now(NY)

def todays_window_bounds():
    """Return concrete (start_dt, end_dt) datetimes for tonight's window in NY time.

    Anchored on today's date in NY. Using real datetimes (not just time-of-day)
    means the comparisons stay correct even if the runner crosses midnight,
    which is what caused earlier scheduled runs to hang for 90 minutes.
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

def sleep_until_window_opens(start_dt):
    """If the job starts before 10:05pm NY (which happens in winter, see README),
    wait until the window actually opens before polling. Uses a concrete
    datetime so it can't loop forever after midnight."""
    while now_ny() < start_dt:
        time.sleep(60)

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

    # If the scheduled runner started so late that the window has already
    # ended for today, bail out cleanly instead of doing nothing or hanging.
    if now_ny() >= end_dt:
        push("Skipped: runner started after 11:05pm NY, missed tonight's window.",
             priority="low", tags="warning")
        print(f"{now_ny()}: started after window end {end_dt}, exiting.")
        return

    sleep_until_window_opens(start_dt)

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
