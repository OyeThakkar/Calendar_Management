"""
CinemaCon Schedule Scraper
Scrapes the schedule of events from https://www.cinemacon.com/en/schedule-of-events
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup
from dateutil import parser as date_parser

logger = logging.getLogger(__name__)

CINEMACON_SCHEDULE_URL = "https://www.cinemacon.com/en/schedule-of-events"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Default year to use when parsing dates without an explicit year
DEFAULT_YEAR = 2026


@dataclass
class CinemaConEvent:
    """Represents a single CinemaCon scheduled event."""

    title: str
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    location: str = "Caesars Palace, Las Vegas, NV"
    description: str = ""
    tags: list = field(default_factory=list)

    def __repr__(self) -> str:
        start = self.start_time.strftime("%Y-%m-%d %H:%M") if self.start_time else "TBD"
        end = self.end_time.strftime("%H:%M") if self.end_time else "TBD"
        return f"CinemaConEvent(title={self.title!r}, start={start}, end={end})"


def fetch_schedule_page(url: str = CINEMACON_SCHEDULE_URL, timeout: int = 30) -> str:
    """
    Fetch the HTML content of the CinemaCon schedule page.

    Args:
        url: The URL to fetch.
        timeout: Request timeout in seconds.

    Returns:
        HTML content as a string.

    Raises:
        requests.RequestException: If the page cannot be fetched.
    """
    logger.info("Fetching schedule from %s", url)
    response = requests.get(url, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    logger.info("Successfully fetched page (%d bytes)", len(response.content))
    return response.text


def _parse_time_range(time_str: str, date: datetime) -> tuple[Optional[datetime], Optional[datetime]]:
    """
    Parse a time range string (e.g. '9:00 a.m. – 11:30 a.m.' or '6:30–8:45 p.m.')
    and combine it with the given date.

    Returns:
        A tuple of (start_datetime, end_datetime).
    """
    time_str = time_str.strip()
    # Normalise various dash/hyphen characters to a plain hyphen
    time_str = re.sub(r"[–—−]", "-", time_str)

    # Split into start/end parts
    parts = re.split(r"\s*-\s*", time_str, maxsplit=1)

    def _parse_single(t: str, fallback_period: str = "") -> Optional[datetime]:
        """Parse a single time string, optionally inheriting an AM/PM indicator."""
        t = t.strip()
        # Normalise a.m./p.m. → am/pm
        t = re.sub(r"\ba\.m\.", "am", t, flags=re.IGNORECASE)
        t = re.sub(r"\bp\.m\.", "pm", t, flags=re.IGNORECASE)
        if not re.search(r"(am|pm)", t, re.IGNORECASE) and fallback_period:
            t = f"{t} {fallback_period}"
        try:
            parsed = date_parser.parse(t, default=date)
            return date.replace(hour=parsed.hour, minute=parsed.minute, second=0, microsecond=0)
        except (ValueError, OverflowError):
            return None

    if len(parts) == 1:
        start = _parse_single(parts[0])
        return start, None

    # Determine AM/PM from end token to inherit into start when missing.
    # Match both "am"/"pm" and "a.m."/"p.m." variants.
    end_period_match = re.search(r"(a\.?m\.?|p\.?m\.?)", parts[1], re.IGNORECASE)
    if end_period_match:
        raw = end_period_match.group(0)
        fallback = "pm" if raw.lower().startswith("p") else "am"
    else:
        fallback = ""

    start = _parse_single(parts[0], fallback)
    end = _parse_single(parts[1])
    return start, end


def _extract_year_from_page(soup: BeautifulSoup) -> int:
    """
    Try to detect the event year from the page content.
    Falls back to DEFAULT_YEAR if not found.
    """
    text = soup.get_text(" ", strip=True)
    match = re.search(r"\b(202\d)\b", text)
    if match:
        return int(match.group(1))
    return DEFAULT_YEAR


def _build_date(day_text: str, year: int) -> Optional[datetime]:
    """
    Parse a day header string such as 'Monday, March 31' into a datetime.
    """
    try:
        return date_parser.parse(f"{day_text} {year}")
    except (ValueError, OverflowError):
        return None


def parse_schedule(html: str) -> list[CinemaConEvent]:
    """
    Parse the CinemaCon schedule HTML into a list of CinemaConEvent objects.

    The parser handles several common markup patterns:
    - Day headings followed by event rows/cards
    - Table-based schedules
    - Simple list-based schedules
    """
    soup = BeautifulSoup(html, "lxml")
    year = _extract_year_from_page(soup)
    events: list[CinemaConEvent] = []

    # ------------------------------------------------------------------ #
    # Strategy 1: look for structured schedule containers / data tables   #
    # ------------------------------------------------------------------ #
    events = _parse_table_schedule(soup, year)
    if events:
        logger.info("Parsed %d events via table strategy", len(events))
        return events

    # ------------------------------------------------------------------ #
    # Strategy 2: day-heading + event-card pattern                        #
    # ------------------------------------------------------------------ #
    events = _parse_card_schedule(soup, year)
    if events:
        logger.info("Parsed %d events via card strategy", len(events))
        return events

    # ------------------------------------------------------------------ #
    # Strategy 3: generic heuristic – look for bold/heading day lines     #
    # followed by indented time/title pairs                               #
    # ------------------------------------------------------------------ #
    events = _parse_heuristic(soup, year)
    logger.info("Parsed %d events via heuristic strategy", len(events))
    return events


# --------------------------------------------------------------------------- #
# Parsing strategies                                                            #
# --------------------------------------------------------------------------- #

_DAY_PATTERN = re.compile(
    r"\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)"
    r"[,\s]+([A-Z][a-z]+\s+\d{1,2})\b",
    re.IGNORECASE,
)

_TIME_PATTERN = re.compile(
    r"\d{1,2}:\d{2}\s*(?:a\.?m\.?|p\.?m\.?)?"
    r"(?:\s*[–—−-]\s*\d{1,2}:\d{2}\s*(?:a\.?m\.?|p\.?m\.?)?)?",
    re.IGNORECASE,
)


def _parse_table_schedule(soup: BeautifulSoup, year: int) -> list[CinemaConEvent]:
    """Parse schedule from <table> elements."""
    events: list[CinemaConEvent] = []
    for table in soup.find_all("table"):
        current_date: Optional[datetime] = None
        for row in table.find_all("tr"):
            cells = row.find_all(["td", "th"])
            if not cells:
                continue
            row_text = " ".join(c.get_text(" ", strip=True) for c in cells)

            # Check if this row is a day header
            day_match = _DAY_PATTERN.search(row_text)
            if day_match and len(cells) <= 2:
                candidate = f"{day_match.group(1)}, {day_match.group(2)}"
                current_date = _build_date(candidate, year)
                continue

            if current_date is None:
                continue

            # Expect at least a time cell and a title cell
            time_text = cells[0].get_text(" ", strip=True) if cells else ""
            title_text = cells[1].get_text(" ", strip=True) if len(cells) > 1 else ""
            location_text = cells[2].get_text(" ", strip=True) if len(cells) > 2 else ""

            if not _TIME_PATTERN.search(time_text) or not title_text:
                continue

            start, end = _parse_time_range(time_text, current_date)
            event = CinemaConEvent(
                title=title_text,
                start_time=start,
                end_time=end,
                location=location_text or "Caesars Palace, Las Vegas, NV",
                description=f"Source: {CINEMACON_SCHEDULE_URL}",
            )
            events.append(event)

    return events


def _parse_card_schedule(soup: BeautifulSoup, year: int) -> list[CinemaConEvent]:
    """
    Parse schedule where events are grouped under day heading elements
    (h2/h3/h4 or elements with a date class) followed by event cards/divs.
    """
    events: list[CinemaConEvent] = []
    current_date: Optional[datetime] = None

    # Candidate heading tags and class keywords
    heading_tags = {"h1", "h2", "h3", "h4", "h5"}
    date_class_re = re.compile(r"date|day|header", re.IGNORECASE)

    for element in soup.find_all(True):
        tag = element.name
        if tag is None:
            continue

        text = element.get_text(" ", strip=True)

        # Check if this element is a day heading
        is_heading = tag in heading_tags or any(
            date_class_re.search(c) for c in element.get("class", [])
        )
        if is_heading:
            day_match = _DAY_PATTERN.search(text)
            if day_match:
                candidate = f"{day_match.group(1)}, {day_match.group(2)}"
                new_date = _build_date(candidate, year)
                if new_date:
                    current_date = new_date
                continue

        if current_date is None:
            continue

        # Skip if this element is itself a heading
        if tag in heading_tags:
            continue

        # Look for time + title pattern in the element text
        time_match = _TIME_PATTERN.search(text)
        if not time_match:
            continue

        # Skip very large containers (they contain child events)
        if len(element.find_all(True)) > 10:
            continue

        time_str = time_match.group(0)
        title = text.replace(time_str, "").strip(" :–—-")
        if not title or len(title) < 3:
            continue

        # Try to find a location sub-element
        location = "Caesars Palace, Las Vegas, NV"
        loc_el = element.find(class_=re.compile(r"location|venue|room", re.IGNORECASE))
        if loc_el:
            location = loc_el.get_text(" ", strip=True)

        start, end = _parse_time_range(time_str, current_date)
        event = CinemaConEvent(
            title=title,
            start_time=start,
            end_time=end,
            location=location,
            description=f"Source: {CINEMACON_SCHEDULE_URL}",
        )
        events.append(event)

    return events


def _parse_heuristic(soup: BeautifulSoup, year: int) -> list[CinemaConEvent]:
    """
    Last-resort heuristic parser: walk all text nodes, detect day lines
    and time+title lines.
    """
    events: list[CinemaConEvent] = []
    current_date: Optional[datetime] = None

    lines = [
        line.strip()
        for line in soup.get_text("\n").splitlines()
        if line.strip()
    ]

    for line in lines:
        day_match = _DAY_PATTERN.search(line)
        if day_match:
            candidate = f"{day_match.group(1)}, {day_match.group(2)}"
            new_date = _build_date(candidate, year)
            if new_date:
                current_date = new_date
            continue

        if current_date is None:
            continue

        time_match = _TIME_PATTERN.search(line)
        if not time_match:
            continue

        time_str = time_match.group(0)
        title = line.replace(time_str, "").strip(" :–—-|•")
        if not title or len(title) < 3:
            continue

        start, end = _parse_time_range(time_str, current_date)
        event = CinemaConEvent(
            title=title,
            start_time=start,
            end_time=end,
            location="Caesars Palace, Las Vegas, NV",
            description=f"Source: {CINEMACON_SCHEDULE_URL}",
        )
        events.append(event)

    return events


def scrape_events(url: str = CINEMACON_SCHEDULE_URL) -> list[CinemaConEvent]:
    """
    High-level function: fetch and parse the CinemaCon schedule.

    Args:
        url: URL of the CinemaCon schedule page.

    Returns:
        List of CinemaConEvent objects.
    """
    html = fetch_schedule_page(url)
    return parse_schedule(html)
