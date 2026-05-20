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
  NTFY_TOPIC          your private ntfy topic name
  TEST_NOW            set to "true" by a manual run to skip the time gate
"""

import os
import sys
import time
import requests
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

CHANNEL = "caseoh_"
NY = ZoneInfo("America/New_York")
WINDOW_START = dtime(22, 0)   # 10:00 PM New York
WINDOW_END = dtime(23, 0)     # 11:00 PM New York
POLL_INTERVAL_SECONDS = 180   # check every 3 minutes

CLIENT_ID = os.environ["TWITCH_CLIENT_ID"]
CLIENT_SECRET = os.environ["TWITCH_CLIENT_SECRET"]
NTFY_TOPIC = os.environ["NTFY_TOPIC"]
TEST_NOW = os.environ.get("TEST_NOW", "false").lower() == "true"


def now_ny():
    return datetime.now(NY)


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


def sleep_until_window_opens():
    """If the job starts before 10pm NY (which happens in winter, see README),
    wait until the window actually opens before polling."""
    while now_ny().time() < WINDOW_START:
        time.sleep(60)


def main():
    token = get_token()

    # Manual test run: one check, one notification, done. No waiting.
    if TEST_NOW:
        live = is_live(token)
        push(f"TEST run: caseoh_ live status is {live}.", tags="test_tube")
        print(f"{now_ny()}: TEST run, live={live}")
        return

    sleep_until_window_opens()

    while now_ny().time() < WINDOW_END:
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
