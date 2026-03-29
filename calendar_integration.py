"""
Calendar Integration
Converts CinemaCon schedule events into .ics files importable by Outlook (and
any other iCalendar-compatible application such as Google Calendar or Apple
Calendar).
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from icalendar import Calendar, Event, vText

from scraper import CinemaConEvent

logger = logging.getLogger(__name__)

# Default event duration when an end-time cannot be parsed from the schedule
DEFAULT_DURATION_HOURS = 1

# Calendar metadata
CALENDAR_PRODID = "-//CinemaCon Schedule//cinemacon.com//EN"
CALENDAR_NAME = "CinemaCon Events"


_LAS_VEGAS_TZ = ZoneInfo("America/Los_Angeles")


def _make_utc(dt: datetime) -> datetime:
    """Ensure a datetime is UTC-aware.  Naive datetimes are assumed to be in
    US/Pacific (America/Los_Angeles, i.e. Las Vegas) time and are converted
    correctly for both PDT (UTC-7) and PST (UTC-8) periods."""
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc)
    # Attach the Las Vegas timezone so DST rules are applied automatically
    return dt.replace(tzinfo=_LAS_VEGAS_TZ).astimezone(timezone.utc)


def event_to_vevent(event: CinemaConEvent) -> Event:
    """
    Convert a CinemaConEvent to an icalendar VEVENT component.

    Args:
        event: The CinemaCon event to convert.

    Returns:
        An icalendar Event object.
    """
    vevent = Event()

    vevent.add("uid", str(uuid.uuid4()))
    vevent.add("summary", event.title)

    if event.start_time:
        start_utc = _make_utc(event.start_time)
        vevent.add("dtstart", start_utc)

        if event.end_time:
            end_utc = _make_utc(event.end_time)
        else:
            end_utc = start_utc + timedelta(hours=DEFAULT_DURATION_HOURS)
        vevent.add("dtend", end_utc)
    else:
        # All-day placeholder when no time is available
        today = datetime.now(tz=timezone.utc).date()
        vevent.add("dtstart", today)
        vevent.add("dtend", today + timedelta(days=1))

    vevent.add("location", vText(event.location))

    description_parts = []
    if event.description:
        description_parts.append(event.description)
    if event.tags:
        description_parts.append("Tags: " + ", ".join(event.tags))
    if description_parts:
        vevent.add("description", "\n".join(description_parts))

    vevent.add("dtstamp", datetime.now(tz=timezone.utc))

    return vevent


def build_calendar(events: list[CinemaConEvent], calendar_name: str = CALENDAR_NAME) -> Calendar:
    """
    Build an icalendar Calendar object from a list of CinemaConEvent objects.

    Args:
        events: List of events to include.
        calendar_name: Display name for the calendar.

    Returns:
        An icalendar Calendar object.
    """
    cal = Calendar()
    cal.add("prodid", CALENDAR_PRODID)
    cal.add("version", "2.0")
    cal.add("x-wr-calname", calendar_name)
    cal.add("x-wr-timezone", "America/Los_Angeles")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")

    for event in events:
        vevent = event_to_vevent(event)
        cal.add_component(vevent)

    logger.info("Built calendar with %d events", len(events))
    return cal


def save_calendar(cal: Calendar, output_path: Optional[Path] = None) -> Path:
    """
    Serialise the calendar to an .ics file.

    Args:
        cal: The icalendar Calendar object to save.
        output_path: Destination file path.  Defaults to
                     ``cinemacon_events.ics`` in the current directory.

    Returns:
        The path to the saved .ics file.
    """
    if output_path is None:
        output_path = Path("cinemacon_events.ics")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    ics_bytes = cal.to_ical()
    output_path.write_bytes(ics_bytes)
    logger.info("Calendar saved to %s", output_path)
    return output_path


def create_calendar_file(
    events: list[CinemaConEvent],
    output_path: Optional[Path] = None,
    calendar_name: str = CALENDAR_NAME,
) -> Path:
    """
    Convenience function: build and save a calendar from a list of events.

    Args:
        events: List of CinemaCon events.
        output_path: Destination .ics file path.
        calendar_name: Display name for the calendar.

    Returns:
        The path to the saved .ics file.
    """
    cal = build_calendar(events, calendar_name=calendar_name)
    return save_calendar(cal, output_path)
