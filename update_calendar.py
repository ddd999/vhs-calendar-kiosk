#!/usr/bin/env python3
import json, os, urllib.request, datetime as dt
from pathlib import Path
import icalendar, recurring_ical_events, time

URL = "https://calendar.google.com/calendar/ical/cory%40vanhack.ca/public/basic.ics"
OUT = Path(__file__).resolve().parent / "status.json"   # same folder as this script

now = dt.datetime.now().astimezone()

def write(data):
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    os.replace(tmp, OUT)        # atomic, and creates status.json if it doesn't exist

for attempt in range(3):
    try:
        cal = icalendar.Calendar.from_ical(urllib.request.urlopen(URL, timeout=20).read())
        break
    except Exception as ex:
        if attempt < 2:
            time.sleep(5)          # network may still be coming up
            continue
        write({"error": str(ex), "updated": now.isoformat(timespec="seconds")})
        raise SystemExit(1)

events = recurring_ical_events.of(cal).between(now - dt.timedelta(days=1),
                                               now + dt.timedelta(days=30))

# Timed events only (skip all-day), as (start, end, title), sorted by start
timed = []
for e in events:
    s, en = e["DTSTART"].dt, e["DTEND"].dt
    if isinstance(s, dt.datetime):
        timed.append((s.astimezone(), en.astimezone(), str(e.get("SUMMARY", "Booked"))))
timed.sort()
spans = [(s, e) for s, e, _ in timed]

# Walk forward from now, extending through overlapping/back-to-back bookings
end = None
cursor = now
for s, e in spans:
    if s <= cursor < e:
        cursor = end = e

# Next booking = first one starting after the current block (or after now if free)
nxt = next(((s, e) for s, e in spans if s > cursor), None)

# Events to draw on the display: anything still running or starting within 30 days
horizon = now + dt.timedelta(days=30)
upcoming = [
    {"title": t, "start": s.isoformat(), "end": e.isoformat()}
    for s, e, t in timed
    if e > now and s < horizon
]

write({
    "booked": end is not None,
    "until": end.strftime("%H:%M") if end else None,
    "next_start": nxt[0].isoformat() if nxt else None,
    "next_end": nxt[1].isoformat() if nxt else None,
    "events": upcoming,
    "updated": now.isoformat(timespec="seconds"),
})
