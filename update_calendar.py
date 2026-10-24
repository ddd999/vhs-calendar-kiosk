#!/usr/bin/env python3
"""Fetch the public Google Calendar iCal feed and write status.json for the kiosk page.

Run every minute from cron (and once at kiosk start). The page never talks to
Google; it only reads the status.json written here.
"""
import json, os, time, urllib.request, datetime as dt
from pathlib import Path
import icalendar, recurring_ical_events

# Public iCal address (Calendar settings > Integrate calendar). The "@" must be %40.
URL = "https://calendar.google.com/calendar/ical/cory%40vanhack.ca/public/basic.ics"
OUT = Path(__file__).resolve().parent / "status.json"   # written next to this script
DAYS_AHEAD = 30                                         # how far ahead to look


def parse_events(cal, now, days=DAYS_AHEAD):
    """Return timed events as sorted (start, end, title) tuples in local time.

    Recurring events are expanded; all-day events are skipped because they
    don't represent a laser booking slot.
    """
    events = recurring_ical_events.of(cal).between(now - dt.timedelta(days=1),
                                                   now + dt.timedelta(days=days))
    timed = []
    for e in events:
        s, en = e["DTSTART"].dt, e["DTEND"].dt
        if isinstance(s, dt.datetime):   # all-day events are plain dates
            timed.append((s.astimezone(), en.astimezone(), str(e.get("SUMMARY", "Booked"))))
    timed.sort()
    return timed


def compute_status(timed, now, days=DAYS_AHEAD):
    """Pure function (no clock, no network): events + current time -> status dict."""
    timed = sorted(timed)
    spans = [(s, e) for s, e, _ in timed]

    # If a booking is running now, extend through any overlapping or
    # back-to-back bookings so the banner shows when the laser is really free.
    end = None
    cursor = now
    for s, e in spans:
        if s <= cursor < e:
            cursor = end = e

    # First booking that starts after the current block (or after now if free)
    nxt = next(((s, e) for s, e in spans if s > cursor), None)

    # Bookings to list on screen: still running, or starting within the horizon
    horizon = now + dt.timedelta(days=days)
    upcoming = [
        {"title": t, "start": s.isoformat(), "end": e.isoformat()}
        for s, e, t in timed
        if e > now and s < horizon
    ]

    return {
        "booked": end is not None,
        "until": end.strftime("%H:%M") if end else None,
        "next_start": nxt[0].isoformat() if nxt else None,
        "next_end": nxt[1].isoformat() if nxt else None,
        "events": upcoming,
        "updated": now.isoformat(timespec="seconds"),   # the page uses this to detect stale data
    }


def write(data):
    # Write to a temp file then rename, so the page never reads a half-written file
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    os.replace(tmp, OUT)


def main():
    now = dt.datetime.now().astimezone()

    # Retry: at boot the network/DNS may not be ready yet
    for attempt in range(3):
        try:
            cal = icalendar.Calendar.from_ical(urllib.request.urlopen(URL, timeout=20).read())
            break
        except Exception as ex:
            if attempt < 2:
                time.sleep(5)
                continue
            # Record the failure so the page shows an error instead of stale data
            write({"error": str(ex), "updated": now.isoformat(timespec="seconds")})
            raise SystemExit(1)

    write(compute_status(parse_events(cal, now), now))


if __name__ == "__main__":
    main()
