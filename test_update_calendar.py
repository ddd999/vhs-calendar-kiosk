import datetime as dt
import icalendar
from update_calendar import compute_status, parse_events

TZ = dt.timezone(dt.timedelta(hours=-7))


def t(hour, minute=0, day=24):
    return dt.datetime(2026, 10, day, hour, minute, tzinfo=TZ)


def ev(start, end, title="Busy"):
    return (start, end, title)


def test_free_when_no_events():
    s = compute_status([], t(14, 30))
    assert s["booked"] is False
    assert s["until"] is None
    assert s["next_start"] is None
    assert s["events"] == []


def test_booked_during_event():
    s = compute_status([ev(t(14), t(15))], t(14, 30))
    assert s["booked"] is True
    assert s["until"] == "15:00"


def test_free_before_event_and_next_is_reported():
    s = compute_status([ev(t(16), t(17))], t(14, 30))
    assert s["booked"] is False
    assert s["next_start"] == t(16).isoformat()
    assert s["next_end"] == t(17).isoformat()


def test_back_to_back_bookings_chain():
    spans = [ev(t(14), t(15)), ev(t(15), t(16))]
    assert compute_status(spans, t(14, 30))["until"] == "16:00"


def test_overlapping_bookings_chain():
    spans = [ev(t(14), t(15, 30)), ev(t(15), t(16))]
    assert compute_status(spans, t(14, 30))["until"] == "16:00"


def test_gap_does_not_chain():
    spans = [ev(t(14), t(15)), ev(t(15, 30), t(16))]
    s = compute_status(spans, t(14, 30))
    assert s["until"] == "15:00"
    assert s["next_start"] == t(15, 30).isoformat()


def test_next_booking_skips_current_chain():
    spans = [ev(t(14), t(15)), ev(t(15), t(16)), ev(t(18), t(19))]
    s = compute_status(spans, t(14, 30))
    assert s["until"] == "16:00"
    assert s["next_start"] == t(18).isoformat()


def test_booking_ending_exactly_now_is_free():
    assert compute_status([ev(t(14), t(15))], t(15))["booked"] is False


def test_booking_starting_exactly_now_is_booked():
    assert compute_status([ev(t(15), t(16))], t(15))["booked"] is True


def test_event_spanning_midnight():
    spans = [ev(t(23), t(1, day=25))]
    s = compute_status(spans, t(23, 30))
    assert s["booked"] is True
    assert s["until"] == "01:00"


def test_events_list_excludes_past_and_beyond_horizon():
    spans = [
        ev(t(9), t(10), "past"),
        ev(t(14), t(15), "current"),
        ev(t(9, day=26), t(10, day=26), "soon"),
        ev(t(9, day=30) + dt.timedelta(days=30), t(10, day=30) + dt.timedelta(days=30), "far"),
    ]
    titles = [e["title"] for e in compute_status(spans, t(14, 30))["events"]]
    assert titles == ["current", "soon"]


ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//test//EN
BEGIN:VEVENT
UID:weekly@test
DTSTAMP:20261001T000000Z
DTSTART:20261019T170000Z
DTEND:20261019T180000Z
RRULE:FREQ=WEEKLY;COUNT=4
SUMMARY:Weekly
END:VEVENT
BEGIN:VEVENT
UID:allday@test
DTSTAMP:20261001T000000Z
DTSTART;VALUE=DATE:20261025
DTEND;VALUE=DATE:20261026
SUMMARY:All day
END:VEVENT
END:VCALENDAR
"""


def test_parse_expands_recurring_and_skips_all_day():
    cal = icalendar.Calendar.from_ical(ICS)
    now = dt.datetime(2026, 10, 24, 12, 0, tzinfo=dt.timezone.utc)
    timed = parse_events(cal, now, days=30)
    # Oct 19 is before the window; Oct 26, Nov 2 and Nov 9 remain
    assert [title for _, _, title in timed] == ["Weekly"] * 3
    assert timed[0][0] == dt.datetime(2026, 10, 26, 17, 0, tzinfo=dt.timezone.utc)
